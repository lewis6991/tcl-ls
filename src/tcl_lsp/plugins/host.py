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
from typing import IO, cast

from tcl_lsp.analysis.facts.parsing import split_tcl_list
from tcl_lsp.analysis.metadata_commands import (
    MetadataBind,
    MetadataContext,
    MetadataPackage,
    MetadataPlugin,
    MetadataProcedure,
    MetadataRef,
    MetadataSelector,
    MetadataSource,
    parse_selector_tokens,
    validate_context_body_selector,
    validate_context_owner_selector,
    validate_procedure_selector,
)
from tcl_lsp.analysis.model import BINDING_KINDS, BindingKind
from tcl_lsp.common import Position
from tcl_lsp.metadata_paths import bundled_metadata_dir
from tcl_lsp.parser import Parser, word_static_text
from tcl_lsp.parser.model import BracedWord, Command, Word

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
_MISSING = object()


@dataclass(frozen=True, slots=True)
class PluginProcedureEffect:
    procedure: MetadataProcedure
    parameter_source_selector: MetadataSelector | None = None


type PluginEffect = (
    MetadataBind
    | MetadataRef
    | MetadataSource
    | MetadataPackage
    | MetadataContext
    | PluginProcedureEffect
)


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
        parse_result = Parser().parse_document(path='plugin:effect', text=effect_item.text)
        if parse_result.diagnostics:
            message = '; '.join(diagnostic.message for diagnostic in parse_result.diagnostics)
            raise RuntimeError(f'Invalid Tcl plugin effect: {message}')
        if len(parse_result.script.commands) != 1:
            raise RuntimeError('Tcl plugin effects must be a single metadata clause command.')

        command = parse_result.script.commands[0]
        command_words = _plugin_command_words(command)
        effect_name = command_words[0]
        if effect_name == 'bind':
            effects.append(_parse_plugin_bind_effect(command))
            continue
        if effect_name == 'ref':
            effects.append(_parse_plugin_ref_effect(command))
            continue
        if effect_name == 'source':
            effects.append(_parse_plugin_source_effect(command))
            continue
        if effect_name == 'package':
            effects.append(_parse_plugin_package_effect(command))
            continue
        if effect_name == 'enter':
            effects.append(_parse_plugin_enter_effect(command))
            continue
        if effect_name == 'procedure':
            effects.append(_parse_plugin_procedure_effect(command))
            continue
        raise RuntimeError(
            f'Unknown Tcl plugin effect `{effect_name}`. '
            'Plugins may return bind, ref, source, package, enter, or procedure.'
        )

    return tuple(effects)


def _parse_plugin_bind_effect(command: Command) -> MetadataBind:
    command_name = 'plugin effect'
    words = _plugin_command_words(command)
    selector, consumed = parse_selector_tokens(words[1:], command_name=command_name)
    _validate_plugin_selector(selector, key='bind')
    kind: BindingKind | None = None
    if consumed == len(words) - 2:
        kind = _parse_plugin_binding_kind(words[-1], command_name=command_name)
    elif consumed != len(words) - 1:
        raise RuntimeError(f'Bind plugin effects must be `bind selector ?kind?`, got `{words[0]}`.')
    elif kind is None:
        raise RuntimeError('Bind plugin effects must declare an explicit binding kind.')
    return MetadataBind(selector=selector, kind=kind)


def _parse_plugin_ref_effect(command: Command) -> MetadataRef:
    command_name = 'plugin effect'
    words = _plugin_command_words(command)
    selector, consumed = parse_selector_tokens(words[1:], command_name=command_name)
    _validate_plugin_selector(selector, key='ref')
    if consumed != len(words) - 1:
        raise RuntimeError('Ref plugin effects must be `ref selector`.')
    return MetadataRef(selector=selector)


def _parse_plugin_source_effect(command: Command) -> MetadataSource:
    command_name = 'plugin effect'
    words = _plugin_command_words(command)
    if len(words) < 3:
        raise RuntimeError('Source plugin effects must be `source selector caller|definition`.')
    selector, consumed = parse_selector_tokens(words[1:-1], command_name=command_name)
    _validate_plugin_selector(selector, key='source')
    if consumed != len(words) - 2:
        raise RuntimeError('Source plugin effects must be `source selector caller|definition`.')
    base = words[-1]
    if base not in ('caller', 'definition'):
        raise RuntimeError('Source plugin effects must end with `caller` or `definition`.')
    return MetadataSource(selector=selector, base=base)


def _parse_plugin_package_effect(command: Command) -> MetadataPackage:
    command_name = 'plugin effect'
    words = _plugin_command_words(command)
    if len(words) == 3 and words[1] == 'literal':
        return MetadataPackage(selector=None, literal_package=words[2])
    if len(words) >= 3 and words[1] == 'select':
        selector, consumed = parse_selector_tokens(words[2:], command_name=command_name)
        _validate_plugin_selector(selector, key='package')
        if consumed != len(words) - 2:
            raise RuntimeError(
                'Package plugin effects must be `package literal name` or `package select selector`.'
            )
        if selector.list_mode or not selector.selects_single_argument:
            raise RuntimeError('Package plugin effects must select a single argument.')
        return MetadataPackage(selector=selector, literal_package=None)
    raise RuntimeError(
        'Package plugin effects must be `package literal name` or `package select selector`.'
    )


def _parse_plugin_enter_effect(command: Command) -> MetadataContext:
    command_name = 'plugin effect'
    words = _plugin_command_words(command)
    if len(words) < 4 or words[2] != 'body':
        raise RuntimeError(
            'Enter plugin effects must be `enter language body selector ? owner selector ?`.'
        )

    context_name = words[1]
    body_selector, consumed = parse_selector_tokens(words[3:], command_name=command_name)
    _validate_plugin_selector(body_selector, key='enter body')
    owner_selector: MetadataSelector | None = None
    index = 3 + consumed
    if index < len(words):
        if words[index] != 'owner':
            raise RuntimeError(
                'Enter plugin effects must be `enter language body selector ? owner selector ?`.'
            )
        owner_selector, owner_consumed = parse_selector_tokens(
            words[index + 1 :],
            command_name=command_name,
        )
        _validate_plugin_selector(owner_selector, key='enter owner')
        if owner_consumed != len(words) - index - 1:
            raise RuntimeError(
                'Enter plugin effects must be `enter language body selector ? owner selector ?`.'
            )
        validate_context_owner_selector(owner_selector, command_name)
    validate_context_body_selector(body_selector, command_name)
    return MetadataContext(
        body_selector=body_selector,
        context_name=context_name,
        owner_selector=owner_selector,
    )


def _parse_plugin_procedure_effect(command: Command) -> PluginProcedureEffect:
    if len(command.words) != 2:
        raise RuntimeError(
            'Procedure plugin effects must be '
            '`procedure { name select selector|literal value|-; '
            'params select selector|literal value|-; '
            '? body select selector ?; ? language body-language ?; '
            '? _params-source select selector ? }`.'
        )

    config_text = _metadata_body_text(command.words[1])
    parse_result = Parser().parse_document(path='plugin:procedure', text=config_text)
    if parse_result.diagnostics:
        message = '; '.join(diagnostic.message for diagnostic in parse_result.diagnostics)
        raise RuntimeError(f'Invalid procedure plugin effect: {message}')

    member_name_selector: MetadataSelector | None | object = _MISSING
    member_name_literal: str | None | object = _MISSING
    parameter_selector: MetadataSelector | None | object = _MISSING
    parameter_literal: str | None | object = _MISSING
    parameter_source_selector: MetadataSelector | None = None
    body_selector: MetadataSelector | None = None
    body_context: str | None = None

    for command in parse_result.script.commands:
        command_words = _plugin_command_words(command)
        nested_name = command_words[0]
        if nested_name == 'name':
            if member_name_selector is not _MISSING:
                raise RuntimeError('Procedure plugin effects may only declare one `name` setting.')
            member_name_selector, member_name_literal = _parse_plugin_procedure_value(
                command_words[1:],
                key='name',
                allow_literal=True,
                allow_none=True,
            )
            continue
        if nested_name == 'params':
            if parameter_selector is not _MISSING:
                raise RuntimeError(
                    'Procedure plugin effects may only declare one `params` setting.'
                )
            parameter_selector, parameter_literal = _parse_plugin_procedure_value(
                command_words[1:],
                key='params',
                allow_literal=True,
                allow_none=True,
            )
            continue
        if nested_name == '_params-source':
            if parameter_source_selector is not None:
                raise RuntimeError(
                    'Procedure plugin effects may only declare one `_params-source` setting.'
                )
            if len(command_words) < 3 or command_words[1] != 'select':
                raise RuntimeError(
                    'Procedure plugin effects must use `_params-source select selector`.'
                )
            parameter_source_selector, consumed = parse_selector_tokens(
                command_words[2:],
                command_name='plugin effect',
            )
            if consumed != len(command_words) - 2:
                raise RuntimeError(
                    'Procedure plugin effects must use `_params-source select selector`.'
                )
            if (
                parameter_source_selector.list_mode
                or not parameter_source_selector.selects_single_argument
            ):
                raise RuntimeError(
                    'Procedure plugin effects must use `_params-source select selector` '
                    'with a single argument selector.'
                )
            continue
        if nested_name == 'body':
            if body_selector is not None:
                raise RuntimeError('Procedure plugin effects may only declare one `body` setting.')
            body_selector, body_literal = _parse_plugin_procedure_value(
                command_words[1:],
                key='body',
                allow_literal=False,
                allow_none=False,
            )
            if body_literal is not None:
                raise RuntimeError('Procedure plugin effects must use `body select selector`.')
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

    if member_name_selector is _MISSING or parameter_selector is _MISSING:
        raise RuntimeError('Procedure plugin effects must declare `name` and `params`.')
    if body_context is not None and body_selector is None:
        raise RuntimeError(
            'Procedure plugin effects may only declare `language` when `body` is present.'
        )

    return PluginProcedureEffect(
        procedure=MetadataProcedure(
            member_name_selector=cast(MetadataSelector | None, member_name_selector),
            member_name_literal=cast(str | None, member_name_literal),
            parameter_selector=cast(MetadataSelector | None, parameter_selector),
            parameter_literal=cast(str | None, parameter_literal),
            body_selector=body_selector,
            body_context=body_context,
        ),
        parameter_source_selector=parameter_source_selector,
    )


def _plugin_command_words(command: Command) -> list[str]:
    words: list[str] = []
    for word in command.words:
        static_text = word_static_text(word)
        if static_text is None:
            raise RuntimeError('Tcl plugin effects must be fully static.')
        words.append(static_text)
    return words


def _parse_plugin_procedure_value(
    words: list[str] | tuple[str, ...],
    *,
    key: str,
    allow_literal: bool,
    allow_none: bool,
) -> tuple[MetadataSelector | None, str | None]:
    if len(words) == 1 and words[0] == '-':
        if not allow_none:
            raise RuntimeError(f'Procedure plugin effects do not support `{key} -`.')
        return None, None

    if len(words) >= 2 and words[0] == 'select':
        selector, consumed = parse_selector_tokens(words[1:], command_name='plugin effect')
        _validate_plugin_selector(selector, key=key)
        if consumed != len(words) - 1:
            raise RuntimeError(f'Procedure plugin effects must use `{key} select selector`.')
        validate_procedure_selector(selector, command_name='plugin effect', role=key)
        return selector, None

    if allow_literal and len(words) == 2 and words[0] == 'literal':
        return None, words[1]

    literal_fragment = '|literal value' if allow_literal else ''
    none_fragment = '|-' if allow_none else ''
    raise RuntimeError(
        f'Procedure plugin effects must use '
        f'`{key} select selector{literal_fragment}{none_fragment}`.'
    )


def _parse_plugin_binding_kind(text: str, *, command_name: str) -> BindingKind:
    if text not in BINDING_KINDS:
        raise RuntimeError(f'Unknown metadata binding kind `{text}` for `{command_name}`.')
    return text


def _validate_plugin_selector(selector: MetadataSelector, *, key: str) -> None:
    if selector.after_options:
        raise RuntimeError(
            f'Plugin effect `{key}` does not support `after-options`; '
            'plugin selectors operate on the full command word list.'
        )


def _metadata_body_text(word: Word) -> str:
    if not isinstance(word, BracedWord):
        raise RuntimeError('Procedure plugin effects must use a braced configuration body.')
    raw_text = word.raw_text
    if raw_text.startswith('{'):
        raw_text = raw_text[1:]
    if raw_text.endswith('}'):
        raw_text = raw_text[:-1]
    return raw_text


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
