import functools
import hashlib
import os
import re
import shutil
import subprocess
import threading
from collections import OrderedDict
from collections.abc import Callable, Sequence
from contextlib import suppress
from pathlib import Path
from subprocess import PIPE, Popen
from typing import TYPE_CHECKING

import odoo
from odoo.tools import misc
from odoo.tools.config import config
from odoo.tools.misc import file_path
from odoo.tools.sass_embedded import SassCompileError

if TYPE_CHECKING:
    from odoo.libs.profiling import SourceMapGenerator

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
    """Resolve the rtlcss executable: ``PATH``/``bin_path`` first, then ``node_modules``.

    Single source for both the probe (:func:`_check_rtlcss`) and the invocation
    (:meth:`CssPipeline.run_rtlcss`), so Windows resolves the npm ``.cmd`` shim
    consistently instead of the probe failing on plain ``rtlcss``.

    The ``node_modules/.bin`` leg mirrors ``esbuild._find_esbuild`` and
    ``sass_embedded.find_sass``. The pipeline's other two Node tools are
    provisioned by the documented ``npm install`` and looked up there; rtlcss
    was resolved as a bare name only, so a checkout that has a perfectly usable
    ``node_modules/.bin/rtlcss`` never found it. RTL then degraded to LTR
    stylesheets behind a single WARNING, and every RTL integration test — they
    are ``skipUnless(_check_rtlcss())`` — reported success without running.

    Falls back to the bare name so a genuinely absent binary still surfaces
    through :func:`_check_rtlcss`'s ``OSError`` path and its install hint.
    """
    names = ("rtlcss.cmd", "rtlcss") if os.name == "nt" else ("rtlcss",)
    for name in names:
        with suppress(OSError):
            return misc.find_in_path(name)
    node_bin = str(Path(odoo.__path__[0]).parent / "node_modules" / ".bin")
    for name in names:
        if found := shutil.which(name, path=node_bin):
            return found
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
    rx_css_import = re.compile(r"(@import[^;{]+;?)")
    """One ``@import`` rule in *compiled* CSS, for hoisting or commenting out.

    Lives here rather than on :class:`AssetsBundle` with the two passes that
    read it: hoisting is a CSS-spec obligation (``@import`` must precede every
    rule), not bundle orchestration, and the bundle held the pattern only so
    :meth:`sourcemap_bundle` could reach back through ``self._bundle`` for it.
    """

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
                    self.rx_css_import,
                    lambda matchobj: f"/* {matchobj.group(0)} */",
                    content,
                )
                content_bundle_list.append(content)
                content_line_count += content.count("\n") + 1
        return (
            "\n".join(content_bundle_list)
            + f"\n/*# sourceMappingURL={sourcemap_url} */"
        )

    def hoist_import_rules(self, css: str) -> tuple[list[str], str]:
        """Lift every ``@import`` out of *css*, returning ``(rules, remainder)``.

        CSS requires ``@import`` to precede any rule, but concatenating a
        bundle's stylesheets buries each file's imports wherever that file
        landed; the caller re-emits *rules* at the top of the artifact.
        String- and comment-aware, so an ``@import`` written inside a
        ``content: "…"`` value stays where it is.

        Returns the rules as a *list* rather than a joined block so the caller
        can splice them into its own newline join: joining here and then
        concatenating would put a leading newline in front of every bundle
        that has no imports at all, which is most of them.
        """
        import_rules: list[str] = []

        def _hoist(match: re.Match) -> str:
            import_rules.append(match.group(0))
            return ""

        remainder = _rewrite_css_outside_strings(self.rx_css_import, _hoist, css)
        return import_rules, remainder

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
            return self._compile_memoized(compiler, source)
        except (CompileError, SassCompileError) as e:
            error = self._format_compiler_error(str(e))
            _logger.warning(error)
            bundle.css_errors.append(error)
            return ""

    _compiled_cache: OrderedDict[tuple, str] = OrderedDict()
    _COMPILED_CACHE_SIZE = 8
    _compiled_cache_lock = threading.Lock()
    """Guards the LRU bookkeeping of :attr:`_compiled_cache`, never a compile.

    ``get`` then ``move_to_end`` is not one operation: with the threaded server
    (``workers = 0``) another request can evict the key in between, and
    ``move_to_end`` on a gone key raises ``KeyError``. Nothing on the way out
    catches it — :meth:`compile_css` catches ``CompileError`` /
    ``SassCompileError``, and ``web.controllers.binary.content_assets`` only
    ``ValueError`` — so it surfaces as a 500 on the bundle URL (verified by
    injecting the ``KeyError``: it propagates out of ``AssetsBundle.css()``
    untouched). Page rendering is not exposed; ``get_links`` versions a bundle
    from checksums without compiling it.

    The window is narrow — it did not reproduce under the GIL in 32k contended
    iterations, even at ``setswitchinterval(1e-6)`` — but it is a real
    interleaving, and the guard costs a lock acquisition per lookup.

    Deliberately NOT held across ``transform``: compiling ``web.assets_web``'s
    638 KB of concatenated SCSS measures 0.61 s through embedded Dart Sass on
    this machine, and serialising that would cost far more than the duplicated
    work two threads racing on a cold key can do. Both compute, both store the
    same bytes.
    """

    @classmethod
    def _memoized_transform(
        cls, key: tuple, source: str, transform: Callable[[str], str]
    ) -> str:
        """Run *transform* on *source*, reusing an identical earlier run.

        One bundle is compiled several times over with byte-identical input:
        direction (RTL) and vendor-prefixing are post-compile passes, so the
        LTR, RTL, autoprefixed and RTL+autoprefixed attachments of a bundle
        share one Sass compile, as does every website whose customisation left
        the stylesheets alone. Measured on ``web.assets_web``, six variants
        collapse to two distinct compile inputs at ~1.6 s of Dart Sass each.
        Only :attr:`WebAsset.id` being deterministic makes them comparable —
        with a random split marker no two of them were ever byte-equal.

        The same holds one stage later: ``rtlcss`` is a second subprocess over
        the now-deterministic compiled CSS.

        *key* is completed with a digest of *source* rather than the source
        itself, so the cache does not also pin the ~1 MB input.

        Only a *successful* transform is stored: a raising ``transform``
        propagates with nothing written. That is load-bearing rather than
        incidental — callers signal failure by raising ``CompileError``, and
        caching one transient subprocess failure would re-serve the degraded
        result for every later build of that input until the worker restarts.
        This is why ``run_rtlcss`` validates its output *inside* the callable
        instead of after the call.

        Disabled in ``--dev`` mode: the key covers the bundle's own files, not
        a ``@use``-only dependency such as a Bootstrap partial, so a developer
        editing one would otherwise keep getting the previous compile. The DB
        attachment has the same blind spot, but it is at least invalidated by
        restarting; a process-local cache would not be.
        """
        if config["dev_mode"]:
            return transform(source)
        cache = cls._compiled_cache
        key = (*key, hashlib.sha256(source.encode()).hexdigest())
        with cls._compiled_cache_lock:
            if (hit := cache.get(key)) is not None:
                cache.move_to_end(key)
                return hit
        result = transform(source)
        with cls._compiled_cache_lock:
            cache[key] = result
            cache.move_to_end(key)
            while len(cache) > cls._COMPILED_CACHE_SIZE:
                cache.popitem(last=False)
        return result

    @classmethod
    def _compile_memoized(cls, compiler: Callable[[str], str], source: str) -> str:
        """Memoize one stylesheet compile; see :meth:`_memoized_transform`.

        The compiler's identity enters the key through its owning class and
        output style, the two things that change its result.
        """
        asset = getattr(compiler, "__self__", None)
        key = ("compile", type(asset).__name__, getattr(asset, "output_style", None))
        return cls._memoized_transform(key, source, lambda src: compiler(src).strip())

    _RX_APPEARANCE = re.compile(
        r"(?<=[{;\s])appearance\s*:\s*(?P<value>[\w-]+)(?P<important>\s*!important)?"
    )
    """Match one ``appearance`` declaration, consuming neither side of it.

    The declaration boundary is a zero-width lookbehind and the trailing ``;``
    stays out of the match, so consecutive declarations both match. The
    previous form consumed a leading ``[{; \\t]`` AND the trailing ``;``, which
    left the next declaration with no boundary character of its own: in the
    compressed output ``.b{appearance:auto;appearance:textfield}`` only the
    first of the two was prefixed. Expanded output happened to escape this —
    Sass indents with spaces, so a space remained as the lead — which is why
    the gap only ever showed in production builds.

    Widening the class to ``\\s`` also covers an unindented hand-written
    ``.a{\\nappearance:none}``, which the old ``[{; \\t]`` missed outright.

    No stylesheet in this tree currently hits either case (verified: old and
    new match the same 7 declarations in ``web.assets_frontend`` and the same
    13 in ``web.assets_web``, in both debug and production) — this closes a
    latent gap rather than fixing observed output.

    The lookbehind is what keeps the match to declarations: a selector
    (``.appearance:hover``) or an attribute (``[appearance]``) is preceded by
    ``.``/``[``, and an already-prefixed ``-webkit-appearance`` by ``-`` —
    none of which are in ``[{;\\s]``.
    """

    @classmethod
    def _autoprefix_css(cls, source: str) -> str:
        """Add required vendor prefixes to compiled CSS.

        Intentionally minimal — only the ``appearance`` property, not a
        general-purpose autoprefixer. String-aware: an ``appearance:`` inside a
        ``content: "…"`` value is left untouched.

        Not idempotent, and does not check for a hand-written prefix next to
        the standard property: both cases emit a duplicate declaration with the
        same value, which is bloat rather than a rendering difference.
        """

        def _prefix(match: re.Match) -> str:
            value = match.group("value")
            important = match.group("important") or ""
            return (
                f"-webkit-appearance:{value}{important};"
                f"-moz-appearance:{value}{important};"
                f"appearance:{value}{important}"
            )

        return _rewrite_css_outside_strings(cls._RX_APPEARANCE, _prefix, source.strip())

    def run_rtlcss(self, source: str) -> str:
        """Transform CSS for right-to-left languages using rtlcss.

        Memoized on the compiled CSS (see :meth:`_memoized_transform`): with a
        deterministic split marker the input is stable, and every RTL variant
        of a bundle — plain and autoprefixed, and one per website — feeds this
        the same bytes. It is a second subprocess of the same order as the Sass
        compile (~600 ms on ``web.assets_web``).
        """
        if not _check_rtlcss():
            return source

        cmd = [_rtlcss_bin(), "-c", _rtlcss_config_path(), "-"]

        def _transform(src: str) -> str:
            out = _run_cli_pipe(cmd, src, self._RTLCSS_TIMEOUT_S).strip()
            if src.strip() and not out:
                raise CompileError("rtlcss: error processing payload\n")
            return out

        try:
            return self._memoized_transform(("rtlcss",), source, _transform)
        except CompileError as e:
            error = str(e)
            if "error processing payload" not in error:
                error = self._format_compiler_error(error)
            _logger.warning("%s", error)
            self._bundle.css_errors.append(error)
            return ""

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
