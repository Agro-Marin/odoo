import logging
import re
import subprocess
from collections.abc import Callable, Sequence
from subprocess import PIPE, Popen
from typing import Literal, NotRequired, TypedDict

from lxml import etree

from odoo.libs.asset_log import get_asset_logger

_logger = logging.getLogger("odoo.addons.base.models.assetsbundle")

_bundle_log = get_asset_logger("bundle")


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


# ``xml()`` returns a discriminated union of blocks; ``type`` is the
# discriminator ``generate_xml_bundle`` branches on. Two TypedDicts (not
# ``dict[str, Any]``) turn a typo into a static error, not a render KeyError.
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


# Two families kept separate: AssetError (content could not be obtained/decoded/
# parsed) is caught as a group via ``except AssetError``; CompileError (a
# preprocessor subprocess failed) is caught explicitly and must NOT fall into
# that net, hence a separate RuntimeError.
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
        # ``errors="replace"``: non-UTF-8 tool output degrades to replacement
        # chars instead of a UnicodeDecodeError that would bypass callers'
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
        # Name the tool: raw output alone can be ambiguous in ``css_errors``.
        raise CompileError(f"{argv[0]!r}: {cmd_output}")
    return out


# CSS string-literal / comment tokenizer — the spans every whole-text CSS
# rewrite (url(), @import, appearance) and the minifier must treat as opaque.
# Alternation order matters: a left-to-right scan takes whichever of comment/
# string opens first. One definition shared by
# ``StylesheetAsset._minify_css_body`` and ``_rewrite_css_outside_strings`` so
# they never drift.
_CSS_STRING_OR_COMMENT = re.compile(
    r"""/\*.*?\*/|"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'""",
    re.DOTALL,
)


def _rewrite_css_outside_strings(
    target: re.Pattern, repl: Callable[[re.Match], str], text: str
) -> str:
    """Apply ``repl`` to ``target`` matches that lie in CSS *code* only.

    A single left-to-right scan consumes string-literal and comment spans first,
    so a ``url()`` / ``@import`` / ``appearance:`` written *inside* a
    ``content: "…"`` value or a comment passes through untouched. ``target``'s
    own capture groups reach ``repl`` unchanged; the scanner adds none.

    A real ``url("x")`` is still rewritten: its match *starts* at the ``url(``
    token (code), and only the inner ``"x"`` is a protected span the rewrite
    never enters.
    """
    # DOTALL scoped to the string/comment arm via ``(?s:...)`` — only it needs
    # it (block comments and ``\\.`` continuations span newlines). Applying it
    # to the whole combined pattern would silently redefine any ``.`` a future
    # ``target`` carries. ``(?s:...)`` is non-capturing, so ``target``'s group
    # numbers are unchanged.
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
