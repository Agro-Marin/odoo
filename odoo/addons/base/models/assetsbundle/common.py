import functools
import hashlib
import logging
import re
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from subprocess import PIPE, Popen
from typing import Literal, NotRequired, TypedDict

from lxml import etree

from odoo.libs.asset_log import get_asset_logger

_logger = logging.getLogger("odoo.addons.base.models.assetsbundle")

_bundle_log = get_asset_logger("bundle")

_PIPELINE_SOURCES = (
    Path(__file__).parent,
    Path(__file__).parents[3] / "tools" / "assets",
    Path(__file__).parents[3] / "tools" / "sass_embedded.py",
)


@functools.cache
def _pipeline_fingerprint() -> str:
    """Digest of the code that turns asset sources into bundle bytes.

    A bundle's version is otherwise a hash of its members' URLs and mtimes
    only, so it carries no notion of *how* those sources were compiled. Change
    the pipeline without touching a single ``.scss`` and every already-persisted
    attachment stays valid: the old, wrongly-compiled bundle is served forever.
    That is not hypothetical — a fix to ``StylesheetAsset.rx_url`` in this
    package kept serving the broken CSS until the attachments were deleted by
    hand.

    Mixing this digest into :meth:`AssetsBundle.get_checksum` makes a pipeline
    change invalidate every bundle exactly once, the same way a source edit
    does. The cost is one lazy walk of a handful of files per process.

    Native-ESM artifacts need no such seed: their URLs are content-addressed
    (``/web/assets/esm/<digest>/…``), so different output already means a
    different URL.

    Falls back to the release version if the sources cannot be read (frozen or
    zipped deployment): a coarse fingerprint still beats none.
    """
    digest = hashlib.sha256()
    files: list[Path] = []
    for source in _PIPELINE_SOURCES:
        if source.is_dir():
            files.extend(source.glob("*.py"))
        elif source.is_file():
            files.append(source)
    try:
        for path in sorted(files):
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
    except OSError:
        from odoo import release

        _logger.warning(
            "Could not read the asset pipeline sources to fingerprint them; "
            "falling back to the release version. A pipeline change that does "
            "not touch any asset file will not invalidate cached bundles."
        )
        return release.version
    if not files:
        from odoo import release

        return release.version
    return digest.hexdigest()


def _sourcemap_source_root(asset_url: str) -> str:
    """Return the relative ``sourceRoot`` climbing from the bundle URL to ``/``.

    Source map ``sources`` are site-absolute; the browser resolves them against
    ``sourceRoot``, so it needs one ``..`` per directory segment of the URL.
    """
    return "/".join(".." for _ in range(len(asset_url.split("/")) - 2)) + "/"


class BundleFileSpec(TypedDict):
    """One bundle source file, collected by ``ir_qweb._get_asset_content``.

    ``content`` is inline source (empty for file-backed assets, where
    ``filename`` points at the file on disk).
    """

    url: str
    filename: str | None
    content: str
    last_modified: NotRequired[float | None]


class NativeModuleData(TypedDict):
    """The import-map / preload payload returned by ``get_native_module_data``."""

    import_map: dict[str, str]
    preload_urls: list[str]
    bridge_import_map: dict[str, str]


class TemplatesBlock(TypedDict):
    """A run of primary / parentless templates, in source order."""

    type: Literal["templates"]
    templates: list[tuple[etree._Element, str | None, str | None]]


class ExtensionsBlock(TypedDict):
    """A run of ``t-inherit-mode="extension"`` templates, grouped by parent."""

    type: Literal["extensions"]
    extensions: dict[str, list[tuple[etree._Element, str | None]]]


XMLBlock = TemplatesBlock | ExtensionsBlock


class CompileError(RuntimeError):
    """A stylesheet preprocessor (Sass/rtlcss) failed or timed out."""


class AssetError(Exception):
    """An asset's content could not be obtained, decoded or parsed."""


class AssetNotFoundError(AssetError):
    """The asset's backing file or attachment does not exist."""


class XMLAssetError(AssetError):
    """An XML template asset failed to parse or validate."""


def _run_cli_pipe(argv: Sequence[str], source: str, timeout_s: int) -> str:
    """Run *argv* feeding *source* on stdin; return its stdout.

    Shared subprocess plumbing for the stylesheet CLIs (Sass, rtlcss). Every
    failure shape raises ``CompileError``.

    :param argv: command line; ``argv[0]`` names the tool in errors
    :param timeout_s: budget — a hung binary must not pin a worker
    :raises CompileError: launch failure, timeout, or non-zero exit
    """
    try:
        proc = Popen(
            argv,
            stdin=PIPE,
            stdout=PIPE,
            stderr=PIPE,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        raise CompileError(f"Could not execute command {argv[0]!r}") from None
    try:
        out, err = proc.communicate(input=source, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise CompileError(f"{argv[0]!r} timed out after {timeout_s}s") from None
    if proc.returncode:
        cmd_output = out + err
        if not cmd_output:
            cmd_output = f"Process exited with return code {proc.returncode}\n"
        raise CompileError(f"{argv[0]!r}: {cmd_output}")
    return out


_CSS_STRING_OR_COMMENT = re.compile(
    r"""/\*.*?\*/|"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'""",
    re.DOTALL,
)

_SCSS_STRING_OR_COMMENT = re.compile(
    rf"""(?:(?<=\s)|\A)//[^\n]*|{_CSS_STRING_OR_COMMENT.pattern}""",
    re.DOTALL,
)

_URL_FUNCTION = r"""url\(\s*(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|[^)'"\n]*)\)"""

_SCSS_STATEMENT_SPANS = re.compile(
    rf"""{_URL_FUNCTION}|{_SCSS_STRING_OR_COMMENT.pattern}""",
    re.DOTALL,
)
"""Opaque spans for scanners that look for SCSS *statements* (``@import``).

Extends :data:`_SCSS_STRING_OR_COMMENT` with the whole ``url(…)`` function, so
the ``//`` of a protocol (``url(https://…)``) or of a protocol-relative href
(``url(//cdn/x.png)``) is not mistaken for the start of a Sass line comment.
Without it the scanner swallowed the rest of that line and every ``@import``
after it on the same line escaped sanitising.

NOT usable by the ``url()`` *rewriter* (:meth:`StylesheetAsset._fetch_content`):
that pass must reach inside ``url(…)``, which is exactly what this hides.
"""

_PROTECTED_SPAN = "_odoo_protected_span"


def _rewrite_css_outside_strings(
    target: re.Pattern,
    repl: Callable[[re.Match], str],
    text: str,
    tokens: re.Pattern = _CSS_STRING_OR_COMMENT,
) -> str:
    """Apply ``repl`` to ``target`` matches that lie in CSS *code* only.

    A single left-to-right scan consumes string-literal and comment spans first,
    so a ``url()`` / ``@import`` / ``appearance:`` written *inside* a
    ``content: "…"`` value or a comment passes through untouched.

    A real ``url("x")`` is still rewritten: its match *starts* at the ``url(``
    token (code), and only the inner ``"x"`` is a protected span the rewrite
    never enters.

    ``tokens`` selects which spans count as opaque. It defaults to the plain-CSS
    ``_CSS_STRING_OR_COMMENT``; pass ``_SCSS_STRING_OR_COMMENT`` when the text is
    preprocessor *source*, so Sass ``//`` line comments are protected too, or
    :data:`_SCSS_STATEMENT_SPANS` to additionally treat ``url(…)`` as opaque.

    The scanner wraps ``tokens`` in one named group, so a match is dispatched on
    *which arm matched* rather than on what the matched text looks like. The old
    prefix sniff (``token[:2] in ("/*", "//")``) silently mis-routed any token
    arm that did not start with a comment or quote — which is every ``url(…)``
    span. ``target``'s own groups therefore start at 2; read them **by name**
    (``match.group("q")``), never by number.
    """
    scanner = re.compile(
        f"(?P<{_PROTECTED_SPAN}>(?s:{tokens.pattern}))|{target.pattern}",
        target.flags,
    )

    def _dispatch(match: re.Match) -> str:
        span = match.group(_PROTECTED_SPAN)
        return span if span is not None else repl(match)

    return scanner.sub(_dispatch, text)
