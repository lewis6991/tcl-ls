from __future__ import annotations

import base64
import os
import queue
import shutil
import subprocess
import threading
from _thread import LockType
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from tcl_lsp.analysis.facts.parsing import ListItem, split_tcl_list
from tcl_lsp.analysis.metadata_commands import MetadataPlugin
from tcl_lsp.common import Position
from tcl_lsp.metadata_paths import metadata_dir

try:
    import resource
except ImportError:
    resource = None

_ZERO_POSITION = Position(offset=0, line=0, character=0)
_PLUGIN_TIMEOUT_SECONDS = 2.0
_PLUGIN_MEMORY_LIMIT_BYTES = 256 * 1024 * 1024
_PLUGIN_NOFILE_LIMIT = 16
_PLUGIN_STACK_LIMIT_BYTES = 8 * 1024 * 1024
_PLUGIN_STDERR_LINE_LIMIT = 50
_STREAM_CLOSED = object()


@dataclass(frozen=True, slots=True)
class PluginProcedureEffect:
    name_word_index: int
    parameter_word_index: int | None
    parameter_names: tuple[str, ...]
    body_word_index: int
    body_context: str | None


type PluginEffect = PluginProcedureEffect


class TclPluginHost:
    __slots__ = (
        '_bridge_path',
        '_lock',
        '_process',
        '_stderr_lines',
        '_stderr_lock',
        '_stderr_thread',
        '_stdout_queue',
        '_stdout_thread',
        '_tclsh_path',
    )

    def __init__(self) -> None:
        tclsh_path = shutil.which('tclsh')
        if tclsh_path is None:
            raise RuntimeError('The `tclsh` executable is required for Tcl analysis plugins.')
        self._tclsh_path = tclsh_path
        self._bridge_path = metadata_dir() / Path('plugins/host.tm')
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._stdout_queue: queue.Queue[str | object] | None = None
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stderr_lock = threading.Lock()
        self._stderr_lines: deque[str] = deque(maxlen=_PLUGIN_STDERR_LINE_LIMIT)

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def close(self) -> None:
        with self._lock:
            self._stop_process_locked()

    def call_plugin(
        self,
        plugin: MetadataPlugin,
        *,
        words: tuple[str, ...],
        info: dict[str, str],
    ) -> tuple[PluginEffect, ...]:
        response_text = self._call_raw(plugin, words=words, info=info)
        return parse_plugin_effects(response_text)

    def _call_raw(
        self,
        plugin: MetadataPlugin,
        *,
        words: tuple[str, ...],
        info: dict[str, str],
    ) -> str:
        request = self._request_text(plugin, words=words, info=info)
        with self._lock:
            return self._call_raw_locked(plugin, request)

    def _call_raw_locked(self, plugin: MetadataPlugin, request: str) -> str:
        for attempt in range(2):
            process = self._ensure_process_locked()
            try:
                self._send_request_locked(process, request)
                status = self._read_stdout_line_locked(timeout=_PLUGIN_TIMEOUT_SECONDS)
                payload = self._read_stdout_line_locked(timeout=_PLUGIN_TIMEOUT_SECONDS)
            except _PluginHostTimeoutError as error:
                self._stop_process_locked(force=True)
                raise RuntimeError(
                    f'Tcl plugin `{plugin.proc_name}` timed out after {_PLUGIN_TIMEOUT_SECONDS:g}s.'
                ) from error
            except _PluginHostExitedError:
                self._stop_process_locked()
                if attempt == 0:
                    continue
                raise RuntimeError(self._host_failure_message())
            except OSError as error:
                self._stop_process_locked()
                if attempt == 0:
                    continue
                raise RuntimeError('Failed to communicate with the Tcl plugin host.') from error

            decoded_payload = _decode_line(payload)
            if status != 'ok':
                raise RuntimeError(decoded_payload)
            return decoded_payload

        raise RuntimeError(self._host_failure_message())

    def _ensure_process_locked(self) -> subprocess.Popen[str]:
        if self._process is not None and self._process.poll() is None:
            return self._process

        self._stop_process_locked()
        try:
            process = subprocess.Popen(
                [self._tclsh_path, str(self._bridge_path)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                bufsize=1,
                preexec_fn=_plugin_preexec_fn() if os.name == 'posix' else None,
                start_new_session=True,
            )
        except OSError as error:
            raise RuntimeError('Failed to launch Tcl plugin host.') from error

        if process.stdin is None or process.stdout is None or process.stderr is None:
            process.kill()
            process.wait()
            raise RuntimeError('Failed to launch Tcl plugin host.')

        stdout_queue: queue.Queue[str | object] = queue.Queue()
        self._stdout_queue = stdout_queue
        with self._stderr_lock:
            self._stderr_lines.clear()

        self._stdout_thread = threading.Thread(
            target=_stdout_reader,
            args=(process.stdout, stdout_queue),
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=_stderr_reader,
            args=(process.stderr, self._stderr_lines, self._stderr_lock),
            daemon=True,
        )
        self._stdout_thread.start()
        self._stderr_thread.start()
        self._process = process
        return process

    def _send_request_locked(self, process: subprocess.Popen[str], request: str) -> None:
        stdin = process.stdin
        if stdin is None:
            raise OSError('Tcl plugin host stdin is unavailable.')
        stdin.write(request)
        stdin.flush()

    def _read_stdout_line_locked(self, *, timeout: float) -> str:
        stdout_queue = self._stdout_queue
        if stdout_queue is None:
            raise _PluginHostExitedError
        try:
            item = stdout_queue.get(timeout=timeout)
        except queue.Empty as error:
            raise _PluginHostTimeoutError from error
        if item is _STREAM_CLOSED:
            raise _PluginHostExitedError
        assert isinstance(item, str)
        return item

    def _request_text(
        self,
        plugin: MetadataPlugin,
        *,
        words: tuple[str, ...],
        info: dict[str, str],
    ) -> str:
        try:
            script_text = plugin.script_path.read_text(encoding='utf-8')
        except OSError as error:
            raise RuntimeError(
                f'Failed to read Tcl plugin script `{plugin.script_path}`.'
            ) from error

        lines = [
            'call',
            _encode_line(str(plugin.script_path)),
            _encode_line(script_text),
            _encode_line(plugin.proc_name),
        ]
        lines.append(str(len(words)))
        lines.extend(_encode_line(word) for word in words)
        lines.append(str(len(info)))
        for key, value in sorted(info.items()):
            lines.append(_encode_line(key))
            lines.append(_encode_line(value))
        return '\n'.join(lines) + '\n'

    def _host_failure_message(self) -> str:
        message = 'Tcl plugin host exited unexpectedly.'
        stderr_text = self._recent_stderr()
        if stderr_text:
            message = f'{message}\n{stderr_text}'
        return message

    def _recent_stderr(self) -> str:
        with self._stderr_lock:
            if not self._stderr_lines:
                return ''
            return '\n'.join(self._stderr_lines)

    def _stop_process_locked(self, *, force: bool = False) -> None:
        process = self._process
        self._process = None
        self._stdout_queue = None
        self._stdout_thread = None
        self._stderr_thread = None
        if process is None:
            return

        if process.poll() is None:
            try:
                stdin = process.stdin
                if not force and stdin is not None:
                    stdin.write('quit\n')
                    stdin.flush()
                    process.wait(timeout=0.2)
                else:
                    process.terminate()
                    process.wait(timeout=0.2)
            except BrokenPipeError, OSError, subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        else:
            process.wait()


def parse_plugin_effects(text: str) -> tuple[PluginEffect, ...]:
    if not text.strip():
        return ()

    effects: list[PluginEffect] = []
    for effect_item in split_tcl_list(text, _ZERO_POSITION):
        effect_words = split_tcl_list(effect_item.text, effect_item.content_start)
        if len(effect_words) != 2:
            raise RuntimeError('Tcl plugin effects must be `effectName { key value ... }` entries.')

        effect_name = effect_words[0].text
        if effect_name == 'procedure':
            effects.append(_parse_plugin_procedure_effect(effect_words[1]))
            continue
        raise RuntimeError(f'Unknown Tcl plugin effect `{effect_name}`.')

    return tuple(effects)


def _parse_plugin_procedure_effect(config_item: ListItem) -> PluginProcedureEffect:
    config_items = split_tcl_list(config_item.text, config_item.content_start)
    if len(config_items) % 2 != 0:
        raise RuntimeError('Procedure plugin effects must use `key value` pairs.')

    values: dict[str, ListItem] = {}
    for index in range(0, len(config_items), 2):
        key = config_items[index].text
        if key in values:
            raise RuntimeError(f'Procedure plugin effects may only declare one `{key}` setting.')
        values[key] = config_items[index + 1]

    try:
        name_index_item = values['name-index']
        body_index_item = values['body-index']
        params_item = values['params']
    except KeyError as error:
        missing_key = error.args[0]
        raise RuntimeError(f'Procedure plugin effects must declare `{missing_key}`.') from error

    parameter_word_item = values.get('params-word-index')
    context_item = values.get('context')
    parameter_names = tuple(
        item.text for item in split_tcl_list(params_item.text, params_item.content_start)
    )
    return PluginProcedureEffect(
        name_word_index=_parse_non_negative_int(name_index_item.text, key='name-index'),
        parameter_word_index=(
            _parse_non_negative_int(parameter_word_item.text, key='params-word-index')
            if parameter_word_item is not None
            else None
        ),
        parameter_names=parameter_names,
        body_word_index=_parse_non_negative_int(body_index_item.text, key='body-index'),
        body_context=context_item.text if context_item is not None else None,
    )


def _parse_non_negative_int(text: str, *, key: str) -> int:
    try:
        value = int(text)
    except ValueError as error:
        raise RuntimeError(f'Plugin effect `{key}` values must be integers.') from error
    if value < 0:
        raise RuntimeError(f'Plugin effect `{key}` values must be non-negative.')
    return value


def _encode_line(text: str) -> str:
    return base64.b64encode(text.encode('utf-8')).decode('ascii')


def _decode_line(text: str) -> str:
    return base64.b64decode(text.encode('ascii')).decode('utf-8')


def _stdout_reader(stream: IO[str], output_queue: queue.Queue[str | object]) -> None:
    try:
        for line in stream:
            output_queue.put(line.rstrip('\n'))
    finally:
        output_queue.put(_STREAM_CLOSED)


def _stderr_reader(stream: IO[str], lines: deque[str], lock: LockType) -> None:
    for line in stream:
        stripped_line = line.rstrip('\n')
        with lock:
            lines.append(stripped_line)


def _plugin_preexec_fn():
    def _limit_process() -> None:
        if resource is None:
            return
        _setrlimit(resource.RLIMIT_AS, _PLUGIN_MEMORY_LIMIT_BYTES)
        _setrlimit(resource.RLIMIT_DATA, _PLUGIN_MEMORY_LIMIT_BYTES)
        _setrlimit(resource.RLIMIT_STACK, _PLUGIN_STACK_LIMIT_BYTES)
        _setrlimit(resource.RLIMIT_NOFILE, _PLUGIN_NOFILE_LIMIT)

    return _limit_process


def _setrlimit(limit: int, value: int) -> None:
    if resource is None:
        return
    try:
        current_soft, current_hard = resource.getrlimit(limit)
    except OSError, ValueError:
        return

    soft_limit = _bounded_limit(value, current_soft)
    hard_limit = _bounded_limit(value, current_hard)
    if soft_limit is None or hard_limit is None:
        return
    if soft_limit > hard_limit:
        soft_limit = hard_limit
    try:
        resource.setrlimit(limit, (soft_limit, hard_limit))
    except OSError, ValueError:
        return


def _bounded_limit(value: int, current: int) -> int | None:
    if resource is None:
        return None
    if current == resource.RLIM_INFINITY:
        return value
    return min(value, current)


class _PluginHostTimeoutError(RuntimeError):
    pass


class _PluginHostExitedError(RuntimeError):
    pass
