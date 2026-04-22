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
from tcl_lsp.metadata_paths import bundled_metadata_dir
from tcl_lsp.parser import Parser, word_static_text
from tcl_lsp.parser.model import Command

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
    name_word_index: int | None
    body_word_index: int | None
    body_context: str | None
    name_literal: str | None = None
    parameter_word_index: int | None = None
    parameter_names: tuple[str, ...] | None = None


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
        self._bridge_path = bundled_metadata_dir() / Path('plugins/host.tcl')
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
            except _PluginHostExitedError as error:
                self._stop_process_locked()
                if attempt == 0:
                    continue
                raise RuntimeError(self._host_failure_message()) from error
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
            raise RuntimeError('Tcl plugin effects must be `effectName { ... }` entries.')

        effect_name = effect_words[0].text
        if effect_name == 'procedure':
            effects.append(_parse_plugin_procedure_effect(effect_words[1]))
            continue
        raise RuntimeError(f'Unknown Tcl plugin effect `{effect_name}`.')

    return tuple(effects)


def _parse_plugin_procedure_effect(config_item: ListItem) -> PluginProcedureEffect:
    parse_result = Parser().parse_document(path='plugin:procedure', text=config_item.text)
    if parse_result.diagnostics:
        message = '; '.join(diagnostic.message for diagnostic in parse_result.diagnostics)
        raise RuntimeError(f'Invalid procedure plugin effect: {message}')

    name_word_index: int | None = None
    name_literal: str | None = None
    parameter_word_index: int | None = None
    parameter_names: tuple[str, ...] | None = None
    body_word_index: int | None = None
    body_context: str | None = None
    params_declared = False

    for command in parse_result.script.commands:
        command_words = _plugin_command_words(command)
        nested_name = command_words[0]
        if nested_name == 'name':
            if name_word_index is not None or name_literal is not None:
                raise RuntimeError('Procedure plugin effects may only declare one `name` setting.')
            name_word_index, name_literal = _parse_plugin_procedure_value(
                command_words[1:],
                key='name',
                allow_literal=True,
                allow_none=False,
            )
            continue
        if nested_name == 'params':
            if params_declared:
                raise RuntimeError(
                    'Procedure plugin effects may only declare one `params` setting.'
                )
            params_declared = True
            parameter_index, parameter_literal = _parse_plugin_procedure_value(
                command_words[1:],
                key='params',
                allow_literal=True,
                allow_none=False,
            )
            if parameter_literal is not None:
                parameter_names = tuple(
                    item.text for item in split_tcl_list(parameter_literal, _ZERO_POSITION)
                )
            else:
                parameter_word_index = parameter_index
            continue
        if nested_name == '_params-source':
            if len(command_words) != 3 or command_words[1] != 'select':
                raise RuntimeError('Procedure plugin effects must use `_params-source select N`.')
            parameter_word_index = _parse_positive_word_index(
                command_words[2], key='_params-source'
            )
            continue
        if nested_name == 'body':
            if body_word_index is not None:
                raise RuntimeError('Procedure plugin effects may only declare one `body` setting.')
            body_word_index, body_literal = _parse_plugin_procedure_value(
                command_words[1:],
                key='body',
                allow_literal=False,
                allow_none=False,
            )
            if body_literal is not None:
                raise RuntimeError('Procedure plugin effects must use `body select N`.')
            continue
        if nested_name == 'language':
            if body_context is not None:
                raise RuntimeError(
                    'Procedure plugin effects may only declare one `language` setting.'
                )
            if len(command_words) != 2:
                raise RuntimeError('Procedure plugin effects must use `language name`.')
            body_context = command_words[1]
            continue
        raise RuntimeError(f'Unknown Tcl plugin procedure setting `{nested_name}`.')

    if name_word_index is None and name_literal is None:
        raise RuntimeError('Procedure plugin effects must declare `name`.')
    if not params_declared:
        raise RuntimeError('Procedure plugin effects must declare `params`.')

    return PluginProcedureEffect(
        name_word_index=name_word_index,
        name_literal=name_literal,
        parameter_word_index=parameter_word_index,
        parameter_names=parameter_names,
        body_word_index=body_word_index,
        body_context=body_context,
    )


def _plugin_command_words(command: Command) -> list[str]:
    words: list[str] = []
    for word in command.words:
        static_text = word_static_text(word)
        if static_text is None:
            raise RuntimeError('Procedure plugin effects must be fully static.')
        words.append(static_text)
    return words


def _parse_plugin_procedure_value(
    words: list[str] | tuple[str, ...],
    *,
    key: str,
    allow_literal: bool,
    allow_none: bool,
) -> tuple[int | None, str | None]:
    if len(words) == 1 and words[0] == '-':
        if not allow_none:
            raise RuntimeError(f'Procedure plugin effects do not support `{key} -`.')
        return None, None

    if len(words) >= 2 and words[0] == 'select':
        if len(words) != 2:
            raise RuntimeError(f'Procedure plugin effects must use `{key} select N`.')
        return _parse_positive_word_index(words[1], key=key), None

    if allow_literal and len(words) == 2 and words[0] == 'literal':
        return None, words[1]

    literal_fragment = '|literal value' if allow_literal else ''
    none_fragment = '|-' if allow_none else ''
    raise RuntimeError(
        f'Procedure plugin effects must use `{key} select N{literal_fragment}{none_fragment}`.'
    )


def _parse_positive_word_index(text: str, *, key: str) -> int:
    try:
        value = int(text)
    except ValueError as error:
        raise RuntimeError(f'Plugin effect `{key}` values must be integers.') from error
    if value <= 0:
        raise RuntimeError(f'Plugin effect `{key}` values must be positive.')
    return value - 1


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
