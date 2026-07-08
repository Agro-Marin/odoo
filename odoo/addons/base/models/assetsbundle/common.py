from __future__ import annotations

import logging
import re
import subprocess
from collections.abc import Callable, Sequence
from subprocess import PIPE, Popen
from typing import TYPE_CHECKING, Literal, NotRequired, TypedDict

from lxml import etree

from odoo.libs.asset_log import get_asset_logger

if TYPE_CHECKING:
    # Model-class imports must stay typing-only: base/models/__init__
    # imports assetsbundle FIRST, and registering ir.attachment before
    # model 'base' exists aborts registry load (house pattern — see
    # ir_attachment.py's own TYPE_CHECKING block).
    pass


_logger = logging.getLogger("odoo.addons.base.models.assetsbundle")

_bundle_log = get_asset_logger("bundle")


def _sourcemap_source_root(asset_url: str) -> str:
    """Relative root climbing from the served bundle URL back to ``/``.

    Source map ``sources`` entries are site-absolute paths; the browser
    resolves them against ``sourceRoot``, so the root must contain one
    ``..`` per directory segment of the bundle URL.
    """
    return "/".join(".." for _ in range(len(asset_url.split("/")) - 2)) + "/"


class BundleFileSpec(TypedDict):
    """One bundle source file, as collected by ``ir_qweb._get_asset_content``.

    ``content`` is the inline source (empty string for file-backed assets,
    where ``filename`` points at the file on disk); the constructor renames
    it to the asset's ``inline`` attribute.
    """

    url: str
    filename: str | None
    content: str
    last_modified: NotRequired[float | None]


class NativeModuleData(TypedDict):
    """The import-map / preload payload returned by ``get_native_module_data``.

    Fixed shape consumed at three ir_qweb sites; the TypedDict documents the
    contract and lets a type checker catch a misspelled key at the call site.
    """

    import_map: dict[str, str]
    preload_urls: list[str]
    bridge_import_map: dict[str, str]


# ``xml()`` returns a discriminated union of blocks; the ``type`` literal is the
# discriminator the consumer (``generate_xml_bundle``) branches on. Modelling it
# as two TypedDicts (instead of ``dict[str, Any]``) makes a typo in either the
# discriminator or a payload key a static error, not a silent KeyError at render.
class TemplatesBlock(TypedDict):
    """A run of primary / parentless templates, in source order."""

    type: Literal["templates"]
    # (element, asset url, t-inherit parent name | None)
    templates: list[tuple[etree._Element, str | None, str | None]]


class ExtensionsBlock(TypedDict):
    """A run of ``t-inherit-mode="extension"`` templates, grouped by parent."""

    type: Literal["extensions"]
    # {parent template name: [(element, asset url), ...]}
    extensions: dict[str, list[tuple[etree._Element, str | None]]]


XMLBlock = TemplatesBlock | ExtensionsBlock


# Two error families, deliberately kept separate:
#   * AssetError   — an asset's content could not be obtained, decoded or parsed
#                    (catchable as one group via ``except AssetError``)
#   * CompileError — a preprocessor subprocess (Sass/rtlcss) failed; caught
#                    explicitly alongside ``SassCompileError``, never via the
#                    ``except AssetError`` net, hence a separate RuntimeError.
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

    Shared subprocess plumbing for the stylesheet CLIs (Sass, rtlcss):
    launch, feed, bounded wait, kill-and-reap on timeout.  Every failure
    shape raises ``CompileError``; callers translate it into their own
    degradation policy (propagate vs ``css_errors`` + degraded output).

    :param argv: command line; ``argv[0]`` names the tool in errors
    :param source: text piped to stdin
    :param timeout_s: budget — a hung binary must not pin a worker
    :raises CompileError: launch failure, timeout, or non-zero exit
    """
    try:
        # ``errors="replace"``: a tool emitting non-UTF-8 bytes (locale-encoded
        # stderr, binary junk on a crash) degrades to replacement characters
        # instead of raising a UnicodeDecodeError that bypasses every caller's
        # CompileError policy.
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
        # Name the tool: the launch-failure and timeout branches already do,
        # and the raw tool output alone can be ambiguous in ``css_errors``.
        raise CompileError(f"{argv[0]!r}: {cmd_output}")
    return out


# CSS string-literal / comment tokenizer — the two spans every whole-text CSS
# rewrite (url(), @import, appearance) and the minifier must treat as opaque.
# Alternation order matters: a ``"`` inside a comment is consumed by the comment
# arm, a ``/*`` inside a string by the string arm (a left-to-right scan takes
# whichever opens first). One definition, referenced by
# ``StylesheetAsset._minify_css_body`` (masking) and
# ``_rewrite_css_outside_strings`` (skip-in-place) so the two never drift.
_CSS_STRING_OR_COMMENT = re.compile(
    r"""/\*.*?\*/|"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'""",
    re.DOTALL,
)


def _rewrite_css_outside_strings(
    target: re.Pattern, repl: Callable[[re.Match], str], text: str
) -> str:
    """Apply ``repl`` to ``target`` matches that lie in CSS *code* only.

    A single left-to-right scan consumes string-literal and comment spans first
    (the same tokenizer strategy as :meth:`StylesheetAsset._minify_css_body`),
    so a ``url()`` / ``@import`` / ``appearance:`` written *inside* a
    ``content: "…"`` value or a comment is passed through untouched instead of
    being rewritten — the string-unawareness the whole-text ``re.sub`` calls
    used to have (characterized as "known limitations" before this).
    ``target``'s own capture groups reach ``repl`` unchanged: the scanner adds
    none of its own.

    A real ``url("x")`` is still rewritten — its match *starts* at the ``url(``
    token (code); only the inner ``"x"`` is a protected span, which the rewrite
    never needs to enter — so preload byte-matching is unaffected.
    """
    # DOTALL is scoped to the string/comment arm via ``(?s:...)`` — only that
    # arm needs it (block comments ``/\*.*?\*/`` and ``\\.`` line continuations
    # span newlines). The previous ``target.flags | re.DOTALL`` forced DOTALL
    # onto the WHOLE combined pattern, silently redefining any ``.`` a future
    # ``target`` might carry; scoping confines it so the caller's pattern keeps
    # exactly the flags it was compiled with. ``(?s:...)`` is non-capturing, so
    # ``target``'s own group numbers are unchanged.
    scanner = re.compile(
        f"(?s:{_CSS_STRING_OR_COMMENT.pattern})|{target.pattern}",
        target.flags,
    )

    def _dispatch(match: re.Match) -> str:
        token = match.group(0)
        if token[:2] == "/*" or token[:1] in ("'", '"'):
            return token  # protected span — pass through verbatim
        return repl(match)

    return scanner.sub(_dispatch, text)
