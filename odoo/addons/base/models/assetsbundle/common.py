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

import odoo.tools
from odoo.libs.asset_log import get_asset_logger

_logger = logging.getLogger("odoo.addons.base.models.assetsbundle")

_bundle_log = get_asset_logger("bundle")


def _pipeline_sources() -> tuple[Path, ...]:
    tools_file = getattr(odoo.tools, "__file__", None)
    if not tools_file or not __file__:
        return ()
    tools_dir = Path(tools_file).resolve().parent
    package_dir = Path(__file__).resolve().parent
    return (
        package_dir,
        tools_dir / "assets",
        tools_dir / "sass_embedded.py",
        package_dir.parent.parent / "data" / "rtlcss.json",
    )


@functools.cache
def _pipeline_fingerprint() -> str:
    digest = hashlib.sha256()
    files: list[Path] = []
    for source in _pipeline_sources():
        if source.is_dir():
            files.extend(source.glob("*.py"))
        elif source.is_file():
            files.append(source)
        else:
            _logger.warning(
                "Asset pipeline source %s does not exist; changes to it will "
                "not invalidate cached bundles.",
                source,
            )
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
    return "/".join(".." for _ in range(len(asset_url.split("/")) - 2)) + "/"


class BundleFileSpec(TypedDict):
    url: str
    filename: str | None
    content: str
    last_modified: NotRequired[float | None]


class NativeModuleData(TypedDict):
    import_map: dict[str, str]
    preload_urls: list[str]
    bridge_import_map: dict[str, str]


class TemplatesBlock(TypedDict):
    type: Literal["templates"]
    templates: list[tuple[etree._Element, str | None, str | None]]


class ExtensionsBlock(TypedDict):
    type: Literal["extensions"]
    extensions: dict[str, list[tuple[etree._Element, str | None]]]


XMLBlock = TemplatesBlock | ExtensionsBlock


class CompileError(RuntimeError):
    pass


class AssetError(Exception):
    pass


class AssetNotFoundError(AssetError):
    pass


class XMLAssetError(AssetError):
    pass


def _run_cli_pipe(argv: Sequence[str], source: str, timeout_s: int) -> str:
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
    scanner = re.compile(
        f"(?P<{_PROTECTED_SPAN}>(?s:{tokens.pattern}))|{target.pattern}",
        target.flags,
    )

    def _dispatch(match: re.Match) -> str:
        span = match.group(_PROTECTED_SPAN)
        return span if span is not None else repl(match)

    return scanner.sub(_dispatch, text)
