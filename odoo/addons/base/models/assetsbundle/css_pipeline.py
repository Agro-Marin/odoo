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
    # Typing-only sibling import: ``bundle`` imports this module at runtime,
    # so the reverse edge stays under TYPE_CHECKING to avoid an import cycle.
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

    Single source of truth for both the startup probe (:func:`_check_rtlcss`)
    and the invocation (:meth:`AssetsBundle.run_rtlcss`): they used to disagree
    — the probe ran plain ``rtlcss`` while the invocation resolved
    ``rtlcss.cmd`` — so on Windows the probe failed and disabled RTL even when
    the ``.cmd`` shim npm installs was present and usable.
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
    # A binary that launches but exits non-zero on ``--version`` is broken (wrong
    # shim, bad install); treat it as unavailable instead of advertising RTL and
    # failing every later ``run_rtlcss`` call.
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

    Split out of :class:`AssetsBundle` so the stylesheet preprocessor — Sass
    compilation, the ``@import`` sanitizer, autoprefixing, the rtlcss pass, the
    per-file split/minify reassembly, and the degraded-error banner — lives
    behind one boundary, with its subprocess error policy, testable without
    attachment I/O.

    Unlike :class:`AssetAttachmentStore` (which deliberately holds no bundle
    reference), this pipeline IS bound to its bundle: :meth:`preprocess` reads
    the bundle's ``stylesheets`` and rebuilds the bundle's ``css_errors``. It
    does NOT mutate the source ``stylesheets`` list: the Sass-hoisted
    ``@at-rules`` fragment and the per-file compiled content are assembled into
    the pipeline's own (fully private) :attr:`_rendered_assets`, which
    :meth:`sourcemap_bundle` reads back. Keeping the source list immutable
    makes :meth:`preprocess` a pure rebuild — no idempotency guard, and
    ``get_checksum`` sees the same assets no matter when it runs. The bundle
    keeps one pipeline (``AssetsBundle._css``) so that render list survives
    the ``preprocess`` → ``sourcemap_bundle`` call sequence.
    """

    # @import sanitizer pattern. ``([^;{]*;?)`` (group 3) captures the post-quote
    # tail (media query, optional ``;``) up to the statement terminator — like
    # ``AssetsBundle.rx_css_import``. Keeping the trailing media query inside the
    # match makes the dedup key media-aware: two imports of the same url with
    # DIFFERENT media stay distinct, and a deduped removal drops the media query
    # with the statement instead of orphaning it. The ``{`` boundary stops a
    # missing-``;`` import from swallowing a following rule body.
    rx_preprocess_imports = re.compile(r"""(@import\s*['"]([^'"]+)['"]([^;{]*;?))""")
    # SCSS-aware scanner driving the @import sanitizer (:meth:`compile_css`). An
    # ``@import`` written inside a comment or string literal is NOT a directive
    # and must be passed through verbatim: otherwise a commented-out
    # ``// @import "x";`` both trips the local-import security check AND poisons
    # the dedup set, silently dropping a real later import of the same partial.
    # This is the SCSS analogue of :func:`_rewrite_css_outside_strings`, but it
    # also consumes the Sass ``//`` line comment — a Sass-only construct that
    # helper deliberately omits, because ``//`` is ordinary text in plain CSS
    # (e.g. ``url(//cdn/...)``) and must not be read as a comment there. The
    # shared ``_CSS_STRING_OR_COMMENT`` supplies the block-comment + string arms
    # (one source), ``//[^\n]*`` adds the line comment, and
    # ``rx_preprocess_imports`` supplies the directive grammar (also one source).
    # Only the directive arm carries capture groups, so its ref / tail keep group
    # numbers 2 / 3 in the combined pattern. A left-to-right scan consumes
    # whichever span opens first, so a ``//`` inside a string is taken by the
    # string arm and a ``"`` inside a ``//`` comment is taken by the line arm.
    # DOTALL is scoped to the block-comment/string arm (``(?s:...)``): the line
    # arm (``//[^\n]*``) and the directive arm carry no ``.``, and confining the
    # flag stops it from silently redefining a ``.`` added to either arm later
    # (mirrors the scoping in :func:`_rewrite_css_outside_strings`).
    _rx_import_scanner = re.compile(
        rf"//[^\n]*|(?s:{_CSS_STRING_OR_COMMENT.pattern})|{rx_preprocess_imports.pattern}",
    )
    # The split marker is namespaced (``odoo-split:``) so it cannot alias a
    # legitimate CSS loud comment (``/*! <token> */``), which Sass and the
    # minifier deliberately preserve: a bare ``/*! <hex> */`` (e.g. a build-hash
    # stamp) used to be misread as a fragment boundary and abort the whole
    # bundle's CSS compile.  Kept in lockstep with ``StylesheetAsset.get_source``.
    rx_css_split = re.compile(r"/\*! odoo-split:([a-f0-9-]+) \*/")

    # rtlcss subprocess budget; a hung binary must not pin a worker.
    _RTLCSS_TIMEOUT_S: int = 60

    # Marker separating the carried-over previous CSS from the appended error
    # banner. It MUST be used by both the split (which strips a prior banner so
    # repeated errors don't stack) and the join (which re-adds it) — see
    # :meth:`_render_css_error_banner`; a single constant keeps the two in lockstep.
    _CSS_ERROR_HEADER = "\n\n/* ## CSS error message ##*/"

    def __init__(self, bundle: AssetsBundle) -> None:
        """Bind the pipeline to the bundle whose stylesheets it transforms."""
        self._bundle = bundle
        # The ordered render list :meth:`preprocess` assembles — the optional
        # Sass-hoisted @at-rules fragment (as a synthetic StylesheetAsset)
        # followed by the bundle's stylesheets, each carrying its compiled
        # content. :meth:`sourcemap_bundle` reads it back. Held here instead
        # of injected into ``bundle.stylesheets`` so preprocess never mutates
        # the bundle's source list.
        self._rendered_assets: list[StylesheetAsset] = []

    def preprocess(self) -> str:
        """Compile SCSS to CSS, apply RTL and autoprefixing.

        All SCSS files are concatenated and compiled as a single
        document (required because Sass variables are globally scoped with
        ``@import``).  UUID markers (``/*! odoo-split:<uuid> */``) injected by
        ``get_source()`` survive Sass compilation and are used to split the
        compiled output back into per-file fragments — each fragment is
        reassigned to its source asset so that per-file headers and source
        maps work correctly.
        """
        bundle = self._bundle
        # preprocess is the single authority on ``css_errors``: it rebuilds the
        # list from scratch on every call — bundle-level compile/rtl failures
        # (appended below) plus each StylesheetAsset's own fetch errors
        # (harvested below) — so a re-run can never double-report.
        bundle.css_errors.clear()
        # Every call rebuilds the render list from scratch, mirroring the
        # ``css_errors.clear()`` above. preprocess never mutates
        # ``bundle.stylesheets``, so re-runs are idempotent by construction:
        # there is no injected @at-rules asset to drop first, and (under RTL)
        # no stale fragment can re-enter the compile input via the
        # ``plain_css_assets`` filter — the old failure modes a guard once fixed.
        self._rendered_assets = []
        if not bundle.stylesheets:
            return ""

        # Reset per-asset state so the rebuild-from-source contract holds for
        # the leaves too. Each StylesheetAsset records fetch/rewrite errors in
        # its own ``errors`` list and caches fetched content in ``_content``;
        # ``css_errors`` is cleared above but then *extended* from those lists,
        # and ``get_source()`` re-reads uncached (it bypasses the ``content``
        # property to recompile from the original source). Without clearing
        # them here a second call double-reports every leaf fetch error (the
        # ``css_errors.clear()`` above is not enough) and could reuse a stale
        # fragment. Resetting ``_content`` keeps minify()/get_source() in step
        # so a cleared error is re-recorded this run rather than silently lost.
        for asset in bundle.stylesheets:
            asset.errors.clear()
            asset._content = None

        compiled = ""
        assets = [a for a in bundle.stylesheets if isinstance(a, PreprocessedCSS)]
        if assets:
            # The whole concatenation is compiled through ONE compiler (Sass
            # needs the global ``@import`` scope), so ``assets[0].compile`` must
            # be every asset's — i.e. all preprocessed assets share one dialect.
            # Only ScssStylesheetAsset exists today; enforce the invariant so a
            # future second PreprocessedCSS dialect trips here instead of being
            # silently compiled through the first asset's compiler. A plain
            # ``raise`` (not ``assert``) so it still fires under ``python -O``,
            # where asserts are stripped — this guards output correctness, not a
            # mere debug check.
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

        # A bundle-level failure (Sass/rtl compile error, or a forbidden
        # @import) recorded an error *before* the per-file split, leaving
        # ``compiled`` empty. ``css_errors`` can only hold such bundle-level
        # entries at this point — leaf fetch errors live on each asset's own
        # ``errors`` list and are harvested later — so a non-empty list here
        # unambiguously means compilation failed and nothing usable was
        # produced. Short-circuit the split + minify reassembly entirely.
        compile_failed = bool(bundle.css_errors)
        if compile_failed:
            # A bundle-level failure produced no usable ``compiled`` output, so
            # the per-file split assigns no fragments. Short-circuit before the
            # ``minify()`` reassembly: that pass would re-fetch — and so
            # re-error — every leaf whose ``_content`` the empty ``compiled``
            # left unset, double-reporting its fetch error within this single
            # call, and its assembled (raw, uncompiled) result is discarded
            # anyway. Harvest the leaf errors recorded during ``get_source()``
            # and return "": "nothing usable, see css_errors".
            for asset in bundle.stylesheets:
                bundle.css_errors.extend(asset.errors)
            return ""

        # Split compiled output back into per-file fragments using UUID markers
        fragments = self.rx_css_split.split(compiled)
        at_rules = fragments.pop(0)
        # Sass moves @at-rules (e.g. @charset) to the top for CSS 2.1
        # compatibility. They have no source asset, so wrap them in a synthetic
        # StylesheetAsset and prepend it to the RENDER list — never to
        # ``bundle.stylesheets``. Keeping the bundle's source list immutable is
        # what makes preprocess a pure rebuild (idempotent without a guard). The
        # bundle version is unaffected either way: ``get_checksum`` reads the
        # ``__init__`` snapshot (``bundle._version_assets``), not this list.
        rendered = list(bundle.stylesheets)
        if at_rules:
            rendered.insert(0, StylesheetAsset(bundle, inline=at_rules))
        self._rendered_assets = rendered

        # Per-file fragments are matched back to their SOURCE assets only — the
        # synthetic @at-rules asset carries its content inline, never via a
        # split marker.
        assets_by_id = {a.id: a for a in bundle.stylesheets}
        # ``rx_css_split`` yields ``marker, content, marker, content, …``;
        # pair-iterate instead of ``pop(0)`` in a loop, which is O(N²) on a
        # bundle that splits into hundreds of fragments.
        marker_iter = iter(fragments)
        for asset_id, content in zip(marker_iter, marker_iter, strict=True):
            asset = assets_by_id.get(asset_id)
            if asset is None:
                raise RuntimeError(
                    f"CSS asset {asset_id!r} not found in stylesheets — "
                    "compiled output is out of sync with the asset list"
                )
            asset._content = content

        # Autoprefix EVERY stylesheet's rendered content — the Sass-compiled
        # fragments assigned above AND the plain .css assets (whose fetch this
        # ``content`` read triggers). The artifact URL (``.autoprefixed``) and
        # ``unique_descriptor`` claim the whole bundle is prefixed; the old
        # pass ran on the compiled Sass output only, so plain CSS in an
        # autoprefixed bundle was never prefixed. Applied per asset (not on the
        # joined output) so the debug path — ``sourcemap_bundle`` rebuilds from
        # each asset's ``content`` — is prefixed too. String-aware, so string
        # literals and headers are safe (see ``_rewrite_css_outside_strings``).
        if bundle.autoprefix:
            for asset in bundle.stylesheets:
                asset._content = self._autoprefix_css(asset.content)

        bundle_css = "\n".join(asset.minify() for asset in self._rendered_assets)
        # Harvest each asset's own fetch/rewrite errors. The minify pass above
        # (and the get_source() reads earlier) is what triggers content
        # fetching, so every asset's ``errors`` list is fully populated by now.
        # The bundle owns ``css_errors`` and the pipeline collects from the
        # leaves here, rather than each StylesheetAsset reaching up to append.
        # A bundle-level compile failure already returned "" above; reaching
        # here means compilation succeeded, so a leaf-only fetch error still
        # ships the partial bundle (the good assets compiled fine), and css()
        # banners on the harvested error (pinned by
        # test_bundle_harvests_asset_errors).
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

        Iterates the render list :meth:`preprocess` assembled (the optional
        @at-rules fragment + the bundle's stylesheets with their compiled
        content) — owning that iteration here keeps :attr:`_rendered_assets`
        fully private to the pipeline. Adds a per-file source mapping to
        *generator* and appends the ``sourceMappingURL`` link; the caller owns
        the ``css`` / ``css.map`` attachment I/O. Mirrors
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
                # comment out the @import rules hoisted to the top of the
                # bundle (string-aware: an ``@import`` inside a
                # ``content: "…"`` value is left intact, not commented out)
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
            # Comment / string span: the ``@import`` inside it is not a
            # directive — return it untouched. This is what stops a commented
            # ``// @import "x";`` from raising a spurious security error and
            # from poisoning ``seen_imports`` (which would silently drop a real
            # later import of the same partial).
            if token[:2] in ("/*", "//") or token[:1] in ("'", '"'):
                return token
            ref = matchobj.group(2)
            line = f'@import "{ref}"{matchobj.group(3)}'
            # Dedup FIRST, media-aware: ``line`` reconstructs the full statement
            # (group 3 carries the trailing media query), so the key treats the
            # same url with different media as distinct. Deduping ahead of the
            # security check means a forbidden import repeated across several
            # concatenated files is reported ONCE, not once per occurrence —
            # ``css_errors`` is joined verbatim into the degraded-CSS banner, so
            # N copies of the same line used to stack into N banner lines (and
            # N identical server warnings). Re-importing a library partial is
            # likewise the normal SCSS case and dropped silently.
            if line in seen_imports:
                return ""
            seen_imports.add(line)
            # Security: reject genuine local/relative imports — a dotted
            # filename (``foo.scss``) or a path-like ref (``./``, ``/``,
            # ``~``). These must be pulled in through the assets bundle,
            # not via a raw @import the compiler resolves off the load path.
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

    # Vendor-prefix matcher for the ``appearance`` property. Handles both
    # expanded ("  appearance: none;") and compressed ("{appearance:none}")
    # Dart Sass output.  Two correctness details:
    #   * the value group is ``[\w-]+`` (not ``\w+``) so a hyphenated value
    #     like ``menulist-button`` is carried into the prefixed copies intact
    #     instead of being truncated to ``menulist``;
    #   * an optional ``!important`` is captured and replicated onto the
    #     ``-webkit-``/``-moz-`` declarations — otherwise the prefixed copies
    #     silently drop it and lose to a competing rule (notably the common
    #     WebKit form-control reset ``appearance: none !important``).
    # ``-webkit-appearance``/``-moz-appearance`` already present are left
    # untouched: their ``appearance`` is preceded by ``-``, outside the
    # ``[{; \t]`` lead-in class.
    _RX_APPEARANCE = re.compile(r"([{; \t])appearance:\s*([\w-]+)(\s*!important)?(;?)")

    @classmethod
    def _autoprefix_css(cls, source: str) -> str:
        """Post-process compiled CSS to add required vendor prefixes.

        Intentionally minimal — only the ``appearance`` property is
        handled; this is not a general-purpose autoprefixer. String-aware
        (via :func:`_rewrite_css_outside_strings`): an ``appearance:`` written
        inside a ``content: "…"`` string value is left untouched.
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
        # Compare on the stripped forms — the value actually returned. The guard
        # used to test the RAW ``out``, so an rtlcss result of pure whitespace
        # (``"\n"``) read as truthy, skipped this branch, and shipped ``""``
        # silently with no banner; stripping ``source`` too keeps a
        # whitespace-only payload (legitimately empty output) from tripping a
        # false positive.
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
        the error. Idempotent across repeated failures: any banner already in
        ``previous_css`` is stripped (split on :attr:`_CSS_ERROR_HEADER`) before
        a fresh one is appended, so the banners never stack. ``css_errors`` text
        is escaped for a CSS string literal (``\\`` → ``\\\\`` FIRST, then ``"`` →
        ``\\"``, newline → ``\\A``, ``*`` → ``\\*``) so the message cannot break
        out of the ``content:`` value or open a comment. The backslash pass runs
        first so a literal ``\\`` in the error (a Windows path, a regex from Sass)
        becomes ``\\\\`` rather than being read as a CSS escape (``\\f`` etc.) — and
        so it does not double the backslashes the later escapes introduce.

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
