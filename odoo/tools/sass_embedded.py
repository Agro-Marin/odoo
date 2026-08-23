import atexit
import collections
import contextlib
import logging
import re
import shutil
import subprocess
import threading
from pathlib import Path
from subprocess import PIPE, Popen
from typing import Self

import odoo
from odoo.libs._vendor.embedded_sass_pb2 import (
    COMPRESSED,
    CSS,
    EXPANDED,
    INDENTED,
    SCSS,
    InboundMessage,
    OutboundMessage,
)

_logger = logging.getLogger(__name__)

_RX_DEPRECATION = re.compile(r"DEPRECATION WARNING \[([a-z-]+)\]")
_RX_OMITTED = re.compile(r"(\d+) repetitive deprecation warnings omitted")

_COMPILE_TIMEOUT_S = 120.0


def _kill_wedged_sass(proc: Popen) -> None:
    _logger.warning(
        "sass --embedded compile exceeded %ss; killing the wedged process",
        _COMPILE_TIMEOUT_S,
    )
    with contextlib.suppress(Exception):
        proc.kill()


class SassCompileError(Exception):
    pass


class SassProtocolError(Exception):
    pass


class SassNotFoundError(SassProtocolError):
    pass


def _encode_varint(value: int) -> bytes:
    parts = []
    while value > 0x7F:
        parts.append((value & 0x7F) | 0x80)
        value >>= 7
    parts.append(value & 0x7F)
    return bytes(parts)


def _read_varint(stream: object) -> int | None:
    result = 0
    shift = 0
    while True:
        byte = stream.read(1)
        if not byte:
            return None
        b = byte[0]
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result
        shift += 7
        if shift >= 64:
            msg = "Varint too long"
            raise SassProtocolError(msg)


class SassImporter:
    def canonicalize(self, url: str, from_import: bool) -> str | None:
        raise NotImplementedError

    def load(self, canonical_url: str) -> tuple[str, str] | None:
        raise NotImplementedError


def _supports_embedded(sass_path: str) -> bool:
    try:
        proc = subprocess.run(
            [sass_path, "--embedded"],
            input=b"",
            stdout=PIPE,
            stderr=subprocess.STDOUT,
            timeout=10,
            check=False,
        )
    except OSError, subprocess.SubprocessError:
        return False
    if proc.returncode != 0:
        return False
    out = (proc.stdout or b"").lower()
    return b"unavailable" not in out and b"pure js" not in out


def find_sass() -> str | None:
    node_modules = Path(odoo.__path__[0]).parent / "node_modules"
    candidates: list[str] = []
    system_sass = shutil.which("sass")
    if system_sass:
        candidates.append(system_sass)
    candidates += sorted(
        str(p) for p in node_modules.glob("sass-embedded-*/dart-sass/sass")
    )
    for candidate in candidates:
        if _supports_embedded(candidate):
            return candidate
    return shutil.which("sass", path=str(node_modules / ".bin")) or system_sass


class SassEmbeddedCompiler:
    def __init__(self, sass_path: str | None = None) -> None:
        self._sass_path = sass_path
        self._process: Popen | None = None
        self._lock = threading.Lock()
        self._compilation_id = 0
        self._started = False

    def _start(self) -> None:
        if self._started and self._process is not None and self._process.poll() is None:
            return
        self._started = False

        sass_path = self._sass_path
        if sass_path is None:
            sass_path = find_sass()
        if sass_path is None:
            raise SassNotFoundError(
                "Dart Sass not found. It is a required dependency of this fork: "
                "run `npm install` in the Odoo root (declared in package.json) "
                "or install a `sass` binary on PATH."
            )

        try:
            self._process = Popen(
                [sass_path, "--embedded"],
                stdin=PIPE,
                stdout=PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError as e:
            raise SassProtocolError(f"Could not start sass --embedded: {e}") from e

        if self._process.poll() is not None:
            proc = self._process
            self._process = None
            for pipe in (proc.stdin, proc.stdout):
                with contextlib.suppress(OSError):
                    pipe.close()
            proc.wait()
            raise SassProtocolError(
                f"sass --embedded exited immediately with code {proc.returncode}"
            )
        self._started = True

    def _send_packet(self, compilation_id: int, message_bytes: bytes) -> None:
        cid_bytes = _encode_varint(compilation_id)
        payload = cid_bytes + message_bytes
        length_bytes = _encode_varint(len(payload))
        self._process.stdin.write(length_bytes + payload)
        self._process.stdin.flush()

    def _recv_packet(self) -> tuple[int, bytes]:
        length = _read_varint(self._process.stdout)
        if length is None:
            msg = "Unexpected EOF from sass --embedded"
            raise SassProtocolError(msg)

        payload = self._process.stdout.read(length)
        if len(payload) != length:
            raise SassProtocolError(
                f"Short read: expected {length} bytes, got {len(payload)}"
            )

        idx = 0
        compilation_id = 0
        shift = 0
        while idx < len(payload):
            b = payload[idx]
            idx += 1
            compilation_id |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7

        return compilation_id, payload[idx:]

    def close(self) -> None:
        if self._process is not None:
            proc = self._process
            self._process = None
            self._started = False
            for pipe in (proc.stdin, proc.stdout):
                with contextlib.suppress(OSError):
                    pipe.close()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
                proc.wait()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def compile_string(
        self,
        source: str,
        *,
        syntax: str = "scss",
        style: str = "expanded",
        source_map: bool = False,
        importers: list[SassImporter] | None = None,
        load_paths: list[str] | None = None,
        quiet_deps: bool = True,
        url: str = "",
    ) -> str:
        with self._lock:
            self._start()
            self._compilation_id += 1
            compilation_id = self._compilation_id

            watchdog = threading.Timer(
                _COMPILE_TIMEOUT_S, _kill_wedged_sass, (self._process,)
            )
            watchdog.daemon = True
            watchdog.start()
            try:
                return self._do_compile(
                    compilation_id,
                    source,
                    syntax,
                    style,
                    source_map,
                    importers or [],
                    load_paths or [],
                    quiet_deps,
                    url,
                )
            except SassCompileError:
                raise
            except Exception:
                self.close()
                raise
            finally:
                watchdog.cancel()

    def _do_compile(
        self,
        compilation_id: int,
        source: str,
        syntax: str,
        style: str,
        source_map: bool,
        importers: list[SassImporter],
        load_paths: list[str],
        quiet_deps: bool,
        url: str,
    ) -> str:
        syntax_enum = {"scss": SCSS, "indented": INDENTED, "css": CSS}.get(syntax, SCSS)
        style_enum = COMPRESSED if style == "compressed" else EXPANDED
        deprecations: collections.Counter[str] = collections.Counter()

        request = InboundMessage()
        compile_req = request.compile_request
        compile_req.id = compilation_id

        string_input = compile_req.string
        string_input.source = source
        string_input.syntax = syntax_enum
        if url:
            string_input.url = url

        compile_req.style = style_enum
        compile_req.source_map = source_map
        compile_req.quiet_deps = quiet_deps

        importer_id_map = {}
        for i, imp in enumerate(importers):
            importer_msg = compile_req.importers.add()
            importer_id = i + 1
            importer_msg.importer_id = importer_id
            importer_id_map[importer_id] = imp

        for path in load_paths:
            importer_msg = compile_req.importers.add()
            importer_msg.path = path

        msg_bytes = request.SerializeToString()
        self._send_packet(compilation_id, msg_bytes)

        while True:
            recv_cid, recv_bytes = self._recv_packet()
            outbound = OutboundMessage()
            outbound.ParseFromString(recv_bytes)

            msg_type = outbound.WhichOneof("message")

            if recv_cid != compilation_id and msg_type != "error":
                raise SassProtocolError(
                    f"sass --embedded desynchronized: sent compilation id "
                    f"{compilation_id}, received {recv_cid} ({msg_type})"
                )

            if msg_type == "compile_response":
                resp = outbound.compile_response
                result_type = resp.WhichOneof("result")
                if result_type == "success":
                    if deprecations:
                        _logger.info(
                            "Sass compiled %s with %s deprecation warning(s): %s",
                            url or "<string>",
                            sum(deprecations.values()),
                            ", ".join(
                                f"{name}={count}"
                                for name, count in deprecations.most_common()
                            ),
                        )
                    return resp.success.css
                elif result_type == "failure":
                    raise SassCompileError(
                        resp.failure.formatted or resp.failure.message
                    )
                else:
                    msg = "CompileResponse has no result"
                    raise SassProtocolError(msg)

            elif msg_type == "log_event":
                event = outbound.log_event
                if event.type == 2:
                    _logger.debug("Sass debug: %s", event.message)
                else:
                    text = event.formatted or event.message
                    _logger.debug("Sass warning: %s", text)
                    if category := _RX_DEPRECATION.search(text):
                        deprecations[category.group(1)] += 1
                    elif omitted := _RX_OMITTED.search(text):
                        deprecations["(repeats omitted by sass)"] += int(
                            omitted.group(1)
                        )

            elif msg_type == "canonicalize_request":
                req = outbound.canonicalize_request
                importer = importer_id_map.get(req.importer_id)
                response = InboundMessage()
                canon_resp = response.canonicalize_response
                canon_resp.id = req.id
                if importer is not None:
                    try:
                        canonical_url = importer.canonicalize(req.url, req.from_import)
                        if canonical_url is not None:
                            canon_resp.url = canonical_url
                    except Exception as e:
                        canon_resp.error = str(e)
                self._send_packet(recv_cid, response.SerializeToString())

            elif msg_type == "import_request":
                req = outbound.import_request
                importer = importer_id_map.get(req.importer_id)
                response = InboundMessage()
                import_resp = response.import_response
                import_resp.id = req.id
                if importer is not None:
                    try:
                        # A distinct name from `canonicalize`'s above: one
                        # `result` holding a URL in one branch and a
                        # (contents, syntax) pair in the other reads as one
                        # value and is not.
                        loaded = importer.load(req.url)
                        if loaded is not None:
                            contents, file_syntax = loaded
                            success = import_resp.success
                            success.contents = contents
                            syntax_val = {
                                "scss": SCSS,
                                "indented": INDENTED,
                                "css": CSS,
                            }.get(file_syntax, SCSS)
                            success.syntax = syntax_val
                            success.source_map_url = req.url
                    except Exception as e:
                        import_resp.error = str(e)
                self._send_packet(recv_cid, response.SerializeToString())

            elif msg_type == "error":
                proto_err = outbound.error
                raise SassProtocolError(
                    f"Protocol error ({proto_err.type}): {proto_err.message}"
                )

            else:
                _logger.debug("Ignoring unhandled message type: %s", msg_type)


def _resolve_sass_path(base: str) -> list[str]:
    base_path = Path(base)
    dirname = base_path.parent
    basename = base_path.name
    candidates = []

    if base_path.suffix in (".scss", ".sass", ".css"):
        candidates.extend((base, str(dirname / f"_{basename}")))
        return candidates

    candidates.extend(base + ext for ext in (".scss", ".sass"))
    candidates.extend(str(dirname / f"_{basename}{ext}") for ext in (".scss", ".sass"))

    candidates.extend(str(base_path / f"index{ext}") for ext in (".scss", ".sass"))
    candidates.extend(str(base_path / f"_index{ext}") for ext in (".scss", ".sass"))

    return candidates


class OdooSassImporter(SassImporter):
    def __init__(self, bootstrap_path: str) -> None:
        self.bootstrap_path = bootstrap_path

    def canonicalize(self, url: str, from_import: bool) -> str | None:
        from odoo.tools.files import file_path

        *parent_parts, filename = url.replace("\\", "/").split("/")
        parent_path_str = str(Path(*parent_parts)) if parent_parts else ""

        search_dirs = []
        if parent_path_str:
            with contextlib.suppress(FileNotFoundError):
                search_dirs.append(file_path(parent_path_str))
        with contextlib.suppress(FileNotFoundError):
            search_dirs.append(
                file_path(str(Path(self.bootstrap_path) / parent_path_str))
                if parent_path_str
                else self.bootstrap_path
            )

        for search_dir in search_dirs:
            base = str(Path(search_dir) / filename)
            for candidate in _resolve_sass_path(base):
                candidate_path = Path(candidate)
                if candidate_path.is_file():
                    return f"file://{candidate_path.resolve()}"

        return None

    def load(self, canonical_url: str) -> tuple[str, str] | None:
        file = Path(canonical_url.removeprefix("file://"))
        if not file.is_file():
            return None
        contents = file.read_text(encoding="utf-8")
        syntax = "indented" if file.suffix == ".sass" else "scss"
        return contents, syntax


_sass_compiler: SassEmbeddedCompiler | None = None
_sass_lock = threading.Lock()
_on_stop_registered = False


def get_sass_compiler() -> SassEmbeddedCompiler:
    global _sass_compiler, _on_stop_registered  # noqa: PLW0603  the dart-sass subprocess is a process singleton
    if _sass_compiler is None:
        with _sass_lock:
            if _sass_compiler is None:
                _sass_compiler = SassEmbeddedCompiler()
                atexit.register(close_sass_compiler)
                if not _on_stop_registered:
                    try:
                        from odoo.service.server import CommonServer

                        CommonServer.on_stop(close_sass_compiler)
                        _on_stop_registered = True
                    except Exception:
                        _logger.debug(
                            "Could not register sass close on server stop",
                            exc_info=True,
                        )
    return _sass_compiler


def close_sass_compiler() -> None:
    global _sass_compiler  # noqa: PLW0603  the dart-sass subprocess is a process singleton
    with _sass_lock:
        if _sass_compiler is not None:
            _sass_compiler.close()
            _sass_compiler = None
