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
    # Under TYPE_CHECKING to break the runtime import cycle: ``bundle`` imports
    # this module.
    from odoo.libs.profiling.sourcemap_generator import SourceMapGenerator

    from .bundle import AssetsBundle
from .assets import PreprocessedCSS, StylesheetAsset
from .common import (
    _CSS_STRING_OR_COMMENT,
    CompileError,
    _logger,
    _rewrite_css_outside_strings,
    _run_cli_pipe,
)


@functools.cache
def _rtlcss_bin() -> str:
    """Resolve the rtlcss executable, handling the Windows ``.cmd`` shim.

    Single source for both the probe (:func:`_check_rtlcss`) and the invocation
    (:meth:`AssetsBundle.run_rtlcss`), so Windows resolves the npm ``.cmd`` shim
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
    # A non-zero ``--version`` means a broken binary (wrong shim, bad install);
    # treat it as unavailable rather than failing every later ``run_rtlcss``.
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

    # @import sanitizer pattern. Group 3 (``([^;{]*;?)``) captures the post-quote
    # tail (media query, optional ``;``), making the dedup key media-aware — same
    # url with different media stays distinct, and a deduped removal takes the
    # media query with it. The ``{`` boundary stops a missing-``;`` import from
    # swallowing a following rule body.
    rx_preprocess_imports = re.compile(r"""(@import\s*['"]([^'"]+)['"]([^;{]*;?))""")
    # SCSS-aware scanner driving the @import sanitizer (:meth:`compile_css`). An
    # ``@import`` inside a comment or string literal is not a directive and is
    # passed through verbatim; otherwise a commented ``// @import "x";`` would
    # trip the security check and poison the dedup set. SCSS analogue of
    # :func:`_rewrite_css_outside_strings`, but it also consumes the Sass ``//``
    # line comment (that helper omits it since ``//`` is ordinary text in plain
    # CSS, e.g. ``url(//cdn/...)``). Arms: ``_CSS_STRING_OR_COMMENT`` (block
    # comment + string), ``//[^\n]*`` (line comment), ``rx_preprocess_imports``
    # (directive grammar, the only arm with capture groups — ref/tail stay groups
    # 2/3). Left-to-right scan resolves overlaps. DOTALL is scoped to the
    # block-comment/string arm (``(?s:...)``) so a ``.`` added to another arm
    # later isn't silently affected.
    _rx_import_scanner = re.compile(
        rf"//[^\n]*|(?s:{_CSS_STRING_OR_COMMENT.pattern})|{rx_preprocess_imports.pattern}",
    )
    # Split marker namespaced (``odoo-split:``) so it can't alias a CSS loud
    # comment (``/*! <token> */``) that Sass and the minifier preserve — a bare
    # ``/*! <hex> */`` build-hash stamp must not read as a fragment boundary.
    # Kept in lockstep with ``StylesheetAsset.get_source``.
    rx_css_split = re.compile(r"/\*! odoo-split:([a-f0-9-]+) \*/")

    # rtlcss subprocess budget; a hung binary must not pin a worker.
    _RTLCSS_TIMEOUT_S: int = 60

    # Separates the carried-over previous CSS from the appended error banner.
    # Used by both the split (strips a prior banner so repeats don't stack) and
    # the join (re-adds it) in :meth:`_render_css_error_banner`.
    _CSS_ERROR_HEADER = "\n\n/* ## CSS error message ##*/"

    def __init__(self, bundle: AssetsBundle) -> None:
        """Bind the pipeline to the bundle whose stylesheets it transforms."""
        self._bundle = bundle
        # Ordered render list :meth:`preprocess` assembles (optional @at-rules
        # fragment + the bundle's stylesheets with compiled content), read back
        # by :meth:`sourcemap_bundle`. Held here rather than in
        # ``bundle.stylesheets`` so preprocess never mutates the source list.
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
        # preprocess is the single authority on ``css_errors``: it rebuilds the
        # list from scratch every call — bundle-level compile/rtl failures plus
        # each asset's harvested fetch errors — so a re-run never double-reports.
        bundle.css_errors.clear()
        # Rebuild the render list from scratch too. preprocess never mutates
        # ``bundle.stylesheets``, so re-runs are idempotent by construction.
        self._rendered_assets = []
        if not bundle.stylesheets:
            return ""

        # Reset per-asset state so the rebuild-from-source contract holds for the
        # leaves. ``css_errors`` is cleared above but then *extended* from each
        # asset's ``errors``, so without clearing those here a second call would
        # double-report every leaf fetch error. Resetting ``_content`` keeps
        # minify()/get_source() in step so a cleared error is re-recorded.
        for asset in bundle.stylesheets:
            asset.errors.clear()
            asset._content = None

        compiled = ""
        assets = [a for a in bundle.stylesheets if isinstance(a, PreprocessedCSS)]
        if assets:
            # The whole concatenation is compiled through ONE compiler (Sass
            # needs the global ``@import`` scope), so ``assets[0].compile`` must
            # serve every asset — all preprocessed assets must share one dialect.
            # Enforce it so a future second dialect trips here instead of being
            # silently compiled through the first asset's compiler. Plain
            # ``raise`` (not ``assert``) so it still fires under ``python -O``.
            dialects = {type(a) for a in assets}
            if len(dialects) != 1:
                raise RuntimeError(
                    f"bundle {bundle.name!r} mixes preprocessed-CSS dialects "
                    f"{sorted(t.__name__ for t in dialects)}"
                )
            source = "\n".join(asset.get_source() for asset in assets)
            compiled = self.compile_css(assets[0].compile, source)

        # RTL: merge plain CSS into compiled output, then transform the whole
        if bundle.rtl:
            plain_css_assets = [
                asset
                for asset in bundle.stylesheets
                if not isinstance(asset, PreprocessedCSS)
            ]
            compiled += "\n".join(asset.get_source() for asset in plain_css_assets)
            compiled = self.run_rtlcss(compiled)

        # At this point ``css_errors`` can only hold bundle-level entries (leaf
        # fetch errors are harvested later), so a non-empty list means a
        # bundle-level failure (Sass/rtl error or forbidden @import) left
        # ``compiled`` empty. Short-circuit the split + minify reassembly.
        compile_failed = bool(bundle.css_errors)
        if compile_failed:
            # With no usable ``compiled`` output the split assigns no fragments;
            # the ``minify()`` pass would re-fetch and re-error every leaf (whose
            # ``_content`` is unset) and discard the raw result anyway. Harvest
            # the leaf errors from ``get_source()`` and return "".
            for asset in bundle.stylesheets:
                bundle.css_errors.extend(asset.errors)
            return ""

        # Split compiled output back into per-file fragments using UUID markers
        fragments = self.rx_css_split.split(compiled)
        at_rules = fragments.pop(0)
        # Sass moves @at-rules (e.g. @charset) to the top for CSS 2.1. They have
        # no source asset, so wrap them in a synthetic StylesheetAsset prepended
        # to the RENDER list — never to ``bundle.stylesheets``, keeping the
        # source list immutable so preprocess stays a pure rebuild.
        rendered = list(bundle.stylesheets)
        if at_rules:
            rendered.insert(0, StylesheetAsset(bundle, inline=at_rules))
        self._rendered_assets = rendered

        # Fragments match back to SOURCE assets only; the synthetic @at-rules
        # asset carries its content inline, never via a split marker.
        assets_by_id = {a.id: a for a in bundle.stylesheets}
        # ``rx_css_split`` yields ``marker, content, marker, content, …``;
        # pair-iterate instead of ``pop(0)`` in a loop (O(N²) on hundreds of
        # fragments).
        marker_iter = iter(fragments)
        for asset_id, content in zip(marker_iter, marker_iter, strict=True):
            asset = assets_by_id.get(asset_id)
            if asset is None:
                raise RuntimeError(
                    f"CSS asset {asset_id!r} not found in stylesheets — "
                    "compiled output is out of sync with the asset list"
                )
            asset._content = content

        # Autoprefix EVERY stylesheet's content — Sass-compiled fragments AND
        # plain .css assets (whose fetch this ``content`` read triggers) — since
        # the ``.autoprefixed`` URL claims the whole bundle is prefixed. Applied
        # per asset (not the joined output) so the debug path rebuilt by
        # ``sourcemap_bundle`` from each asset's ``content`` is prefixed too.
        # String-aware, so literals and headers are safe.
        if bundle.autoprefix:
            for asset in bundle.stylesheets:
                asset._content = self._autoprefix_css(asset.content)

        bundle_css = "\n".join(asset.minify() for asset in self._rendered_assets)
        # Harvest each asset's fetch/rewrite errors, now fully populated by the
        # minify pass (and earlier get_source() reads) that triggered fetching.
        # Compilation succeeded (a bundle-level failure returned "" above), so a
        # leaf-only fetch error still ships the partial bundle and css() banners
        # on it (pinned by test_bundle_harvests_asset_errors).
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
                # Comment out the @import rules hoisted to the top of the bundle
                # (string-aware: an ``@import`` inside a ``content: "…"`` value
                # is left intact).
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
        sitting inside a comment or string literal are passed through
        verbatim (see :attr:`_rx_import_scanner`).
        """
        bundle = self._bundle
        seen_imports: set[str] = set()

        def sanitize_import(matchobj: re.Match) -> str:
            token = matchobj.group(0)
            # Comment / string span: the ``@import`` inside it is not a directive
            # — return it untouched so a commented ``// @import "x";`` neither
            # raises a spurious security error nor poisons ``seen_imports``.
            if token[:2] in ("/*", "//") or token[:1] in ("'", '"'):
                return token
            ref = matchobj.group(2)
            line = f'@import "{ref}"{matchobj.group(3)}'
            # Dedup FIRST, media-aware: ``line`` reconstructs the full statement
            # (group 3 carries the trailing media query), so same url + different
            # media stays distinct. Deduping ahead of the security check reports
            # a repeated forbidden import ONCE, not once per occurrence (each
            # would otherwise stack a banner line). Re-imported library partials
            # are the normal SCSS case and dropped silently.
            if line in seen_imports:
                return ""
            seen_imports.add(line)
            # Security: reject local/relative imports — a dotted filename
            # (``foo.scss``) or a path-like ref (``./``, ``/``, ``~``). These
            # must come through the assets bundle, not a raw @import resolved off
            # the compiler's load path.
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

        source = self._rx_import_scanner.sub(sanitize_import, source)

        try:
            return compiler(source).strip()
        except (CompileError, SassCompileError) as e:
            error = self._format_compiler_error(str(e))
            _logger.warning(error)
            bundle.css_errors.append(error)
            return ""

    # Vendor-prefix matcher for the ``appearance`` property, handling expanded
    # and compressed Dart Sass output. The value group is ``[\w-]+`` so a
    # hyphenated value (``menulist-button``) survives intact; an optional
    # ``!important`` is captured and replicated onto the prefixed copies (else
    # they lose to ``appearance: none !important``). Existing
    # ``-webkit-``/``-moz-appearance`` are left untouched — their ``appearance``
    # is preceded by ``-``, outside the ``[{; \t]`` lead-in.
    _RX_APPEARANCE = re.compile(r"([{; \t])appearance:\s*([\w-]+)(\s*!important)?(;?)")

    @classmethod
    def _autoprefix_css(cls, source: str) -> str:
        """Add required vendor prefixes to compiled CSS.

        Intentionally minimal — only the ``appearance`` property, not a
        general-purpose autoprefixer. String-aware: an ``appearance:`` inside a
        ``content: "…"`` value is left untouched.
        """

        def _prefix(match: re.Match) -> str:
            lead, value = match.group(1), match.group(2)
            important = match.group(3) or ""
            semicolon = match.group(4)
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
        # Compare on stripped forms so a whitespace-only rtlcss result doesn't
        # read as truthy and ship "" with no banner; stripping ``source`` too
        # avoids a false positive on a legitimately empty payload.
        out = out.strip()
        if source.strip() and not out:
            # Zero exit but empty output for a non-empty payload — rtlcss
            # swallowed the stylesheet without reporting an error.
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
