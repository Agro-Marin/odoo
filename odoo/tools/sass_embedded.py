"""Embedded Sass Protocol client for Dart Sass.

Provides a high-performance SCSS/Sass compiler using the Sass Embedded
Protocol (protobuf over stdin/stdout). Dart Sass is a required dependency
of this fork (declared in ``package.json``, provisioned by ``npm install``):
a missing or non-startable binary raises :class:`SassNotFoundError` /
:class:`SassProtocolError` rather than silently degrading.

See https://github.com/sass/embedded-protocol for the protocol specification.
"""

import atexit
import contextlib
import logging
import shutil
import subprocess
import threading
from pathlib import Path
from subprocess import PIPE, Popen
from typing import Self

import odoo
from odoo.tools.embedded_sass_pb2 import (
    COMPRESSED,
    CSS,
    EXPANDED,
    INDENTED,
    SCSS,
    InboundMessage,
    OutboundMessage,
)

_logger = logging.getLogger(__name__)

# Wall-clock ceiling for a single compile. Generous (large bundles are slow),
# but bounded: without it a wedged dart-sass would block the stdin/stdout I/O
# forever WHILE HOLDING the client lock, freezing every SCSS compile in the
# process. On timeout the subprocess is killed so the blocked I/O fails, the
# client reaps it, and the caller falls back to the CLI compiler.
_COMPILE_TIMEOUT_S = 120.0


def _kill_wedged_sass(proc: Popen) -> None:
    """Kill a ``sass --embedded`` process that exceeded the compile deadline.

    Runs on a watchdog thread; it only kills the specific captured process and
    never touches the client's shared state, so it cannot race ``_process``.
    """
    _logger.warning(
        "sass --embedded compile exceeded %ss; killing the wedged process",
        _COMPILE_TIMEOUT_S,
    )
    with contextlib.suppress(Exception):
        proc.kill()


class SassCompileError(Exception):
    """Raised when Sass compilation fails."""


class SassProtocolError(Exception):
    """Raised on embedded protocol violations."""


class SassNotFoundError(SassProtocolError):
    """Raised when the required Dart Sass binary cannot be located.

    Distinct from a protocol/compile error so callers can fail loudly on a
    misconfigured deployment instead of mistaking a missing compiler for a
    stylesheet error (Dart Sass is a hard dependency; see the module docstring).
    """


# ---------------------------------------------------------------------------
# Varint helpers (protobuf wire format)
# ---------------------------------------------------------------------------


def _encode_varint(value: int) -> bytes:
    """Encode an unsigned integer as a protobuf varint."""
    parts = []
    while value > 0x7F:
        parts.append((value & 0x7F) | 0x80)
        value >>= 7
    parts.append(value & 0x7F)
    return bytes(parts)


def _read_varint(stream: object) -> int | None:
    """Read an unsigned varint from a binary stream. Returns None on EOF."""
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


# ---------------------------------------------------------------------------
# Sass Importer interface
# ---------------------------------------------------------------------------


class SassImporter:
    """Base class for custom Sass importers."""

    def canonicalize(self, url: str, from_import: bool) -> str | None:
        """Return a canonical URL for the given import, or None."""
        raise NotImplementedError

    def load(self, canonical_url: str) -> tuple[str, str] | None:
        """Return (contents, syntax) for a canonical URL, or None."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Binary discovery
# ---------------------------------------------------------------------------


def _supports_embedded(sass_path: str) -> bool:
    """Whether ``sass_path`` actually speaks the Embedded Sass Protocol.

    The presence of a ``sass`` binary is not enough. Two common cases accept
    the ``--embedded`` flag but cannot serve the protocol, and each would make
    the embedded compiler deadlock/``EPIPE`` writing protobuf to a dead stdin
    and silently degrade EVERY SCSS compile to the slow per-bundle CLI:

    - the **pure-JS** ``sass`` (the npm ``sass`` package, routinely on a dev's
      global ``PATH``) prints "sass --embedded is unavailable in pure JS mode"
      and exits non-zero;
    - a **wrong-platform** bundled binary (e.g. the ``sass-embedded-linux-musl``
      build on a glibc host) fails to exec its inner dart binary (rc 127).

    Probe by launching ``sass --embedded`` with an empty (EOF) stdin: a real
    native Dart Sass boots the protocol host and exits 0 cleanly on EOF with no
    diagnostic; the two bad cases exit non-zero (and the pure-JS one carries a
    recognisable marker). Cheap — the host shuts down immediately on EOF — and
    run at most a handful of times per process (``find_sass`` is called once per
    compiler start).
    """
    try:
        proc = subprocess.run(
            [sass_path, "--embedded"],
            input=b"",
            stdout=PIPE,
            stderr=subprocess.STDOUT,
            timeout=10,
        )
    except OSError, subprocess.SubprocessError:
        return False
    if proc.returncode != 0:
        return False
    out = (proc.stdout or b"").lower()
    return b"unavailable" not in out and b"pure js" not in out


def find_sass() -> str | None:
    """Locate an ``--embedded``-capable Dart Sass binary.

    Searches system ``PATH`` first (system Dart Sass is preferred as it may be
    newer), then the npm-provisioned ``sass-embedded-*`` packages under the
    Odoo root's ``node_modules`` — like
    :func:`odoo.tools.assets.esbuild._find_esbuild`, since a documented ``npm
    install`` provisions the compiler and ``PATH`` alone would miss it. Each
    candidate is verified with :func:`_supports_embedded`, so a pure-JS or
    wrong-platform ``sass`` is never returned. If none speaks the protocol,
    fall back to the pure-JS ``sass`` CLI in ``node_modules/.bin`` (driven per
    bundle via ``--stdin``), then to any system ``sass``.

    :return: path to a ``sass`` binary, or ``None`` if none is found.
    """
    node_modules = Path(odoo.__path__[0]).parent / "node_modules"
    candidates: list[str] = []
    system_sass = shutil.which("sass")
    if system_sass:
        candidates.append(system_sass)
    # Sorted for determinism across the (possibly several) per-platform
    # ``sass-embedded-<os>-<arch>`` packages npm may have unpacked.
    candidates += sorted(
        str(p) for p in node_modules.glob("sass-embedded-*/dart-sass/sass")
    )
    for candidate in candidates:
        if _supports_embedded(candidate):
            return candidate
    # No embedded-capable binary: fall back to the pure-JS ``sass`` CLI (no
    # ``--embedded``; the embedded layer degrades to the per-bundle CLI path),
    # or, failing that, whatever system ``sass`` we found so SCSS still compiles.
    return shutil.which("sass", path=str(node_modules / ".bin")) or system_sass


# ---------------------------------------------------------------------------
# Embedded Sass Compiler
# ---------------------------------------------------------------------------


class SassEmbeddedCompiler:
    """Client for the Sass Embedded Protocol.

    Manages a long-running ``sass --embedded`` subprocess and communicates
    via protobuf-encoded messages over stdin/stdout.

    Usage::

        compiler = SassEmbeddedCompiler()
        css = compiler.compile_string(
            ".a { .b { color: red; } }",
            style="compressed",
        )
        compiler.close()

    Or as a context manager::

        with SassEmbeddedCompiler() as compiler:
            css = compiler.compile_string(source)
    """

    def __init__(self, sass_path: str | None = None) -> None:
        self._sass_path = sass_path
        self._process: Popen | None = None
        self._lock = threading.Lock()
        self._compilation_id = 0
        self._started = False

    def _start(self) -> None:
        """Spawn the ``sass --embedded`` subprocess."""
        # Also restart when the process died since last use (e.g. killed by the
        # compile watchdog, or crashed between compiles): a dead process must not
        # be reused or every subsequent compile would fail on a broken pipe.
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
                stderr=PIPE,
            )
        except OSError as e:
            raise SassProtocolError(f"Could not start sass --embedded: {e}") from e

        # Verify the process started successfully
        if self._process.poll() is not None:
            proc = self._process
            self._process = None
            stderr = proc.stderr.read().decode(errors="replace")
            for pipe in (proc.stdin, proc.stdout, proc.stderr):
                with contextlib.suppress(OSError):
                    pipe.close()
            proc.wait()  # reap the zombie
            raise SassProtocolError(f"sass --embedded exited immediately: {stderr}")
        self._started = True

    def _send_packet(self, compilation_id: int, message_bytes: bytes) -> None:
        """Send a varint-framed packet to the compiler."""
        cid_bytes = _encode_varint(compilation_id)
        payload = cid_bytes + message_bytes
        length_bytes = _encode_varint(len(payload))
        self._process.stdin.write(length_bytes + payload)
        self._process.stdin.flush()

    def _recv_packet(self) -> tuple[int, bytes]:
        """Read a varint-framed packet from the compiler.

        Returns (compilation_id, protobuf_bytes).
        """
        length = _read_varint(self._process.stdout)
        if length is None:
            msg = "Unexpected EOF from sass --embedded"
            raise SassProtocolError(msg)

        # Read the full payload
        payload = self._process.stdout.read(length)
        if len(payload) != length:
            raise SassProtocolError(
                f"Short read: expected {length} bytes, got {len(payload)}"
            )

        # Parse compilation_id from the beginning of payload
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
        """Shut down the compiler subprocess."""
        if self._process is not None:
            proc = self._process
            self._process = None
            self._started = False
            for pipe in (proc.stdin, proc.stdout, proc.stderr):
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
        """Compile a Sass/SCSS string to CSS.

        :param source: the stylesheet source code.
        :param syntax: one of ``scss``, ``indented``, ``css``.
        :param style: one of ``expanded``, ``compressed``.
        :param source_map: whether to generate a source map.
        :param importers: custom importers for resolving ``@import``/``@use``.
        :param load_paths: filesystem paths to search for imports.
        :param quiet_deps: suppress deprecation warnings from dependencies.
        :param url: the URL of the source file (for error messages).
        :return: the compiled CSS string.
        :raises SassCompileError: if compilation fails.
        :raises SassProtocolError: if a protocol error occurs.
        """
        with self._lock:
            self._start()
            self._compilation_id += 1
            compilation_id = self._compilation_id

            # Watchdog: kill the subprocess if this compile blocks past the
            # deadline (see _COMPILE_TIMEOUT_S), so a wedged dart-sass cannot
            # hold self._lock — and thus every other SCSS compile — forever.
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
                # Process crashed or was killed by the watchdog mid-communication
                # — close to reap the zombie process, then re-raise so the caller
                # can react (the embedded → CLI fallback in
                # ``SassStylesheetAsset.compile`` handles a transient
                # embedded-protocol failure; a missing binary raises
                # ``SassNotFoundError`` from ``_start`` and never reaches here).
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
        """Execute a single compilation request/response cycle."""
        # Build the CompileRequest
        syntax_enum = {"scss": SCSS, "indented": INDENTED, "css": CSS}.get(syntax, SCSS)
        style_enum = COMPRESSED if style == "compressed" else EXPANDED

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

        # Build importer list: custom importers first, then load paths
        importer_id_map = {}
        for i, imp in enumerate(importers):
            importer_msg = compile_req.importers.add()
            importer_id = i + 1  # IDs start at 1
            importer_msg.importer_id = importer_id
            importer_id_map[importer_id] = imp

        for path in load_paths:
            importer_msg = compile_req.importers.add()
            importer_msg.path = path

        # Serialize and send
        msg_bytes = request.SerializeToString()
        self._send_packet(compilation_id, msg_bytes)

        # Process responses until we get a CompileResponse
        while True:
            recv_cid, recv_bytes = self._recv_packet()
            outbound = OutboundMessage()
            outbound.ParseFromString(recv_bytes)

            msg_type = outbound.WhichOneof("message")

            if msg_type == "compile_response":
                resp = outbound.compile_response
                result_type = resp.WhichOneof("result")
                if result_type == "success":
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
                if event.type == 2:  # DEBUG
                    _logger.debug("Sass debug: %s", event.message)
                else:
                    # WARNING or DEPRECATION_WARNING — log at debug level
                    # since we use quiet_deps to suppress most noise
                    _logger.debug("Sass warning: %s", event.formatted or event.message)

            elif msg_type == "canonicalize_request":
                req = outbound.canonicalize_request
                importer = importer_id_map.get(req.importer_id)
                response = InboundMessage()
                canon_resp = response.canonicalize_response
                canon_resp.id = req.id
                if importer is not None:
                    try:
                        result = importer.canonicalize(req.url, req.from_import)
                        if result is not None:
                            canon_resp.url = result
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
                        result = importer.load(req.url)
                        if result is not None:
                            contents, file_syntax = result
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


# ---------------------------------------------------------------------------
# Odoo-specific importer
# ---------------------------------------------------------------------------


def _resolve_sass_path(base: str) -> list[str]:
    """Generate candidate paths for Sass partial resolution.

    Given a base path like ``/path/to/foo``, returns candidates in order:
    - /path/to/foo.scss
    - /path/to/foo.sass
    - /path/to/_foo.scss
    - /path/to/_foo.sass
    - /path/to/foo/index.scss
    - /path/to/foo/index.sass
    - /path/to/foo/_index.scss
    - /path/to/foo/_index.sass
    """
    base_path = Path(base)
    dirname = base_path.parent
    basename = base_path.name
    candidates = []

    # If already has an extension, try as-is and with underscore prefix
    if base_path.suffix in (".scss", ".sass", ".css"):
        candidates.extend((base, str(dirname / f"_{basename}")))
        return candidates

    # Try with extensions
    candidates.extend(base + ext for ext in (".scss", ".sass"))
    candidates.extend(str(dirname / f"_{basename}{ext}") for ext in (".scss", ".sass"))

    # Try index files
    candidates.extend(str(base_path / f"index{ext}") for ext in (".scss", ".sass"))
    candidates.extend(str(base_path / f"_index{ext}") for ext in (".scss", ".sass"))

    return candidates


class OdooSassImporter(SassImporter):
    """Sass importer that resolves imports using Odoo's addon paths.

    Mirrors the behavior of the existing ``scss_importer`` closure in
    ``ScssStylesheetAsset.compile()`` but adapted for the Embedded Sass
    Protocol's canonicalize/load two-step interface.
    """

    def __init__(self, bootstrap_path: str) -> None:
        self.bootstrap_path = bootstrap_path

    def canonicalize(self, url: str, from_import: bool) -> str | None:
        """Resolve an import URL to a canonical file:// URL."""
        from odoo.tools.misc import file_path

        *parent_parts, filename = url.replace("\\", "/").split("/")
        parent_path_str = str(Path(*parent_parts)) if parent_parts else ""

        # Try resolving via Odoo's file_path first, then bootstrap
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
        """Load a stylesheet from a canonical file:// URL."""
        file = Path(canonical_url.removeprefix("file://"))
        if not file.is_file():
            return None
        contents = file.read_text(encoding="utf-8")
        syntax = "indented" if file.suffix == ".sass" else "scss"
        return contents, syntax


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_sass_compiler: SassEmbeddedCompiler | None = None
_sass_lock = threading.Lock()
_on_stop_registered = False


def get_sass_compiler() -> SassEmbeddedCompiler:
    """Return the singleton SassEmbeddedCompiler, creating it lazily."""
    global _sass_compiler, _on_stop_registered  # noqa: PLW0603  # lazy singleton init
    if _sass_compiler is None:
        with _sass_lock:
            if _sass_compiler is None:
                _sass_compiler = SassEmbeddedCompiler()
                atexit.register(close_sass_compiler)
                if not _on_stop_registered:
                    # Close the compiler subprocess during the server's
                    # graceful stop. on_stop hooks run before the server's
                    # lingering-child check, so this avoids the spurious
                    # "process may hang" warning and does not rely on atexit
                    # ordering. Lazy import: this tool sits below odoo.service,
                    # and the hook is only needed when a server is running.
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
    """Shut down the singleton SassEmbeddedCompiler if running."""
    global _sass_compiler  # noqa: PLW0603  # tear down the lazy singleton
    with _sass_lock:
        if _sass_compiler is not None:
            _sass_compiler.close()
            _sass_compiler = None
