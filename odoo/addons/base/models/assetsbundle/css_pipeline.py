import functools
import os
import re
import subprocess
from collections.abc import Callable, Sequence
from contextlib import suppress
from subprocess import PIPE, Popen
from typing import TYPE_CHECKING

from odoo.tools import misc
from odoo.tools.misc import file_path
from odoo.tools.sass_embedded import SassCompileError

if TYPE_CHECKING:
    from odoo.libs.profiling.sourcemap_generator import SourceMapGenerator

    from .bundle import AssetsBundle
from .assets import PreprocessedCSS, StylesheetAsset
from .common import (
    _SCSS_STATEMENT_SPANS,
    CompileError,
    _logger,
    _rewrite_css_outside_strings,
    _run_cli_pipe,
)


@functools.cache
def _rtlcss_bin() -> str:
    """Resolve the rtlcss executable, handling the Windows ``.cmd`` shim.

    Single source for both the probe (:func:`_check_rtlcss`) and the invocation
    (:meth:`CssPipeline.run_rtlcss`), so Windows resolves the npm ``.cmd`` shim
    consistently instead of the probe failing on plain ``rtlcss``.
    """
    if os.name == "nt":
        with suppress(OSError):
            return misc.find_in_path("rtlcss.cmd")
    return "rtlcss"


@functools.cache
def _check_rtlcss() -> bool:
    """Probe for the ``rtlcss`` binary. Cached per-process; the warning fires once."""
    try:
        check = Popen([_rtlcss_bin(), "--version"], stdout=PIPE, stderr=PIPE)
        check.communicate(timeout=10)
    except OSError:
        _logger.warning(
            "rtlcss is required for RTL CSS support. Install with: npm install -g rtlcss"
        )
        return False
    except subprocess.TimeoutExpired:
        check.kill()
        check.communicate()
        _logger.warning("rtlcss --version probe timed out; disabling RTL support")
        return False
    if check.returncode:
        _logger.warning(
            "rtlcss --version exited with %s; disabling RTL support",
            check.returncode,
        )
        return False
    return True


@functools.cache
def _rtlcss_config_path() -> str:
    """Absolute path to the rtlcss config, resolved once per process."""
    return file_path("base/data/rtlcss.json")


class CssPipeline:
    """Compile one bundle's stylesheets to CSS: SCSS, autoprefix, RTL, minify.

    Bound to its bundle: :meth:`preprocess` reads the bundle's ``stylesheets``
    and rebuilds ``css_errors``. It does NOT mutate the source ``stylesheets``
    list — the Sass-hoisted ``@at-rules`` fragment and per-file compiled content
    go into the pipeline's private :attr:`_rendered_assets`, which
    :meth:`sourcemap_bundle` reads back. Keeping the source list immutable makes
    :meth:`preprocess` a pure rebuild (no idempotency guard) and gives
    ``get_checksum`` stable assets. The bundle keeps one pipeline
    (``AssetsBundle._css``) so the render list survives the ``preprocess`` →
    ``sourcemap_bundle`` sequence.
    """

    rx_preprocess_imports = re.compile(
        r"""@import\s*['"](?P<ref>[^'"]+)['"](?P<tail>[^;{]*;?)"""
    )
    rx_css_split = re.compile(r"/\*! odoo-split:([a-f0-9-]+) \*/")

    _RTLCSS_TIMEOUT_S: int = 60

    _CSS_ERROR_HEADER = "\n\n/* ## CSS error message ##*/"

    def __init__(self, bundle: AssetsBundle) -> None:
        """Bind the pipeline to the bundle whose stylesheets it transforms."""
        self._bundle = bundle
        self._rendered_assets: list[StylesheetAsset] = []

    def preprocess(self) -> str:
        """Compile SCSS to CSS, apply RTL and autoprefixing.

        All SCSS files are concatenated and compiled as a single document
        (Sass variables are globally scoped via ``@import``). UUID markers
        (``/*! odoo-split:<uuid> */``) injected by ``get_source()`` survive
        compilation and split the output back into per-file fragments, each
        reassigned to its source asset so per-file headers and source maps work.
        """
        bundle = self._bundle
        bundle.css_errors.clear()
        self._rendered_assets = []
        if not bundle.stylesheets:
            return ""

        for asset in bundle.stylesheets:
            asset.errors.clear()
            asset._content = None

        compiled = ""
        assets = [a for a in bundle.stylesheets if isinstance(a, PreprocessedCSS)]
        if assets:
            dialects = {type(a) for a in assets}
            if len(dialects) != 1:
                msg = (
                    f"Bundle {bundle.name!r} mixes preprocessed-CSS dialects "
                    f"{sorted(t.__name__ for t in dialects)}: they compile as one "
                    "document and no compiler reads two syntaxes at once. Split "
                    "them into separate bundles."
                )
                _logger.warning(msg)
                bundle.css_errors.append(msg)
                return ""
            source = "\n".join(asset.get_source() for asset in assets)
            compiled = self.compile_css(assets[0].compile, source)

        if bundle.rtl:
            plain_css_assets = [
                asset
                for asset in bundle.stylesheets
                if not isinstance(asset, PreprocessedCSS)
            ]
            compiled += "\n".join(asset.get_source() for asset in plain_css_assets)
            compiled = self.run_rtlcss(compiled)

        compile_failed = bool(bundle.css_errors)
        if compile_failed:
            for asset in bundle.stylesheets:
                bundle.css_errors.extend(asset.errors)
            return ""

        fragments = self.rx_css_split.split(compiled)
        at_rules = fragments.pop(0)
        rendered = list(bundle.stylesheets)
        if at_rules:
            rendered.insert(0, StylesheetAsset(bundle, inline=at_rules))
        self._rendered_assets = rendered

        assets_by_id = {a.id: a for a in bundle.stylesheets}
        marker_iter = iter(fragments)
        for asset_id, content in zip(marker_iter, marker_iter, strict=True):
            asset = assets_by_id.get(asset_id)
            if asset is None:
                raise RuntimeError(
                    f"CSS asset {asset_id!r} not found in stylesheets — "
                    "compiled output is out of sync with the asset list"
                )
            asset._content = content

        if bundle.autoprefix:
            for asset in bundle.stylesheets:
                asset._content = self._autoprefix_css(asset.content)

        bundle_css = "\n".join(asset.minify() for asset in self._rendered_assets)
        for asset in bundle.stylesheets:
            bundle.css_errors.extend(asset.errors)
        return bundle_css

    def sourcemap_bundle(
        self,
        generator: SourceMapGenerator,
        sourcemap_url: str,
        content_import_rules: str,
    ) -> str:
        """Build the un-minified debug CSS body, populating *generator*.

        Iterates the render list :meth:`preprocess` assembled, adds a per-file
        source mapping to *generator*, and appends the ``sourceMappingURL``
        link; the caller owns the ``css`` / ``css.map`` attachment I/O. Mirrors
        :meth:`JsPipeline.sourcemap_bundle`.

        :param content_import_rules: the ``@import`` rules ``css()`` hoisted,
            re-emitted at the top of the bundle (they must precede any rule)
        """
        content_bundle_list = [content_import_rules]
        content_line_count = content_import_rules.count("\n") + 1
        for asset in self._rendered_assets:
            if asset.content:
                content = asset.with_header(asset.content)
                if asset.url:
                    generator.add_source(asset.url, content, content_line_count)
                content = _rewrite_css_outside_strings(
                    self._bundle.rx_css_import,
                    lambda matchobj: f"/* {matchobj.group(0)} */",
                    content,
                )
                content_bundle_list.append(content)
                content_line_count += content.count("\n") + 1
        return (
            "\n".join(content_bundle_list)
            + f"\n/*# sourceMappingURL={sourcemap_url} */"
        )

    def compile_css(self, compiler: Callable[[str], str], source: str) -> str:
        """Sanitize @import rules, remove duplicates, then compile.

        Only @import statements in actual SCSS *code* are sanitized: ones
        sitting inside a comment, a string literal or a ``url(…)`` are passed
        through verbatim (see :data:`_SCSS_STATEMENT_SPANS`).
        """
        bundle = self._bundle
        seen_imports: set[str] = set()

        def sanitize_import(matchobj: re.Match) -> str:
            ref = matchobj.group("ref")
            line = f'@import "{ref}"{matchobj.group("tail")}'
            if line in seen_imports:
                return ""
            seen_imports.add(line)
            if "." in ref or ref.startswith((".", "/", "~")):
                msg = (
                    f"Local import {ref!r} is forbidden for security reasons."
                    " Remove @import statements from custom files;"
                    " in Odoo, import files via the assets bundle instead."
                )
                _logger.warning(msg)
                bundle.css_errors.append(msg)
                return ""
            return line

        source = _rewrite_css_outside_strings(
            self.rx_preprocess_imports,
            sanitize_import,
            source,
            _SCSS_STATEMENT_SPANS,
        )

        try:
            return compiler(source).strip()
        except (CompileError, SassCompileError) as e:
            error = self._format_compiler_error(str(e))
            _logger.warning(error)
            bundle.css_errors.append(error)
            return ""

    _RX_APPEARANCE = re.compile(
        r"(?P<lead>[{; \t])appearance:\s*(?P<value>[\w-]+)"
        r"(?P<important>\s*!important)?(?P<semicolon>;?)"
    )

    @classmethod
    def _autoprefix_css(cls, source: str) -> str:
        """Add required vendor prefixes to compiled CSS.

        Intentionally minimal — only the ``appearance`` property, not a
        general-purpose autoprefixer. String-aware: an ``appearance:`` inside a
        ``content: "…"`` value is left untouched.
        """

        def _prefix(match: re.Match) -> str:
            lead, value = match.group("lead"), match.group("value")
            important = match.group("important") or ""
            semicolon = match.group("semicolon")
            return (
                f"{lead}-webkit-appearance:{value}{important};"
                f"-moz-appearance:{value}{important};"
                f"appearance:{value}{important}{semicolon}"
            )

        return _rewrite_css_outside_strings(cls._RX_APPEARANCE, _prefix, source.strip())

    def run_rtlcss(self, source: str) -> str:
        """Transform CSS for right-to-left languages using rtlcss."""
        if not _check_rtlcss():
            return source

        cmd = [_rtlcss_bin(), "-c", _rtlcss_config_path(), "-"]

        try:
            out = _run_cli_pipe(cmd, source, self._RTLCSS_TIMEOUT_S)
        except CompileError as e:
            error = self._format_compiler_error(str(e))
            _logger.warning("%s", error)
            self._bundle.css_errors.append(error)
            return ""
        out = out.strip()
        if source.strip() and not out:
            error = "rtlcss: error processing payload\n"
            _logger.warning("%s", error)
            self._bundle.css_errors.append(error)
            return ""
        return out

    def _format_compiler_error(self, stderr: str) -> str:
        """Clean up and contextualize a CSS compiler error message.

        Strips Dart Sass noise ("Load paths", "--trace" hints) and appends
        the bundle name and list of preprocessed source files.
        """
        bundle = self._bundle
        error = stderr.split("Load paths", maxsplit=1)[0].replace(
            "  Use --trace for backtrace.", ""
        )
        error += f"This error occurred while compiling the bundle {bundle.name!r} containing:"
        for asset in bundle.stylesheets:
            if isinstance(asset, PreprocessedCSS):
                error += f"\n    - {asset.url or '<inline sass>'}"
        return error

    @classmethod
    def _render_css_error_banner(
        cls, css_errors: Sequence[str], previous_css: str
    ) -> str:
        """Build the degraded-CSS payload shown when a stylesheet fails to compile.

        Re-serves the last good CSS (``previous_css``) plus a red banner naming
        the error. Idempotent: any banner already in ``previous_css`` is stripped
        (split on :attr:`_CSS_ERROR_HEADER`) before a fresh one is appended, so
        banners never stack. ``css_errors`` is escaped for a CSS string literal
        (``\\`` FIRST, then ``"``, newline → ``\\A``, ``*``) so it cannot break out
        of the ``content:`` value or open a comment. The backslash pass runs
        first so a literal ``\\`` isn't read as a CSS escape and doesn't double
        the backslashes the later escapes introduce.

        :param css_errors: per-asset / bundle compile errors, joined newline-wise
        :param previous_css: decoded raw of the last good attachment (``""`` if none)
        :return: the CSS to persist as the degraded bundle
        """
        error_message = (
            "\n".join(css_errors)
            .replace("\\", "\\\\")
            .replace('"', r"\"")
            .replace("\n", r"\A")
            .replace("*", r"\*")
        )
        carried_over = previous_css.split(cls._CSS_ERROR_HEADER, maxsplit=1)[0]
        banner = f"""
body::before {{
  font-weight: bold;
  content: "A css error occurred, using an old style to render this page";
  position: fixed;
  left: 0;
  bottom: 0;
  z-index: 100000000000;
  background-color: #C00;
  color: #DDD;
}}

css_error_message {{
  content: "{error_message}";
}}
"""
        return cls._CSS_ERROR_HEADER.join([carried_over, banner])
