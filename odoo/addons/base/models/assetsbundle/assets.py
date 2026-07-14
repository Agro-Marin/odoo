import functools
import posixpath
import re
import uuid
from contextlib import suppress
from datetime import UTC
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lxml import etree
from rjsmin import jsmin as rjsmin

from odoo.libs.constants import (
    DOTTED_ASSET_EXTENSIONS as EXTENSIONS,
)
from odoo.tools import profiler
from odoo.tools.assets.esbuild import (
    minify_js,
)
from odoo.tools.assets.esm_graph import (
    _parse_odoo_module_header,
    url_to_module_path,
)
from odoo.tools.json import scriptsafe as json
from odoo.tools.misc import file_open, file_path
from odoo.tools.sass_embedded import SassCompileError, SassNotFoundError, find_sass

if TYPE_CHECKING:
    # Model-class imports must stay typing-only: base/models/__init__
    # imports assetsbundle FIRST, and registering ir.attachment before
    # model 'base' exists aborts registry load (house pattern — see
    # ir_attachment.py's own TYPE_CHECKING block).
    # Typing-only sibling import (avoids a runtime cycle with ``bundle``).
    from .bundle import AssetsBundle
    from odoo.addons.base.models.ir_attachment import IrAttachment
from .common import (
    _CSS_STRING_OR_COMMENT,
    AssetError,
    AssetNotFoundError,
    XMLAssetError,
    _logger,
    _rewrite_css_outside_strings,
    _run_cli_pipe,
)


class WebAsset:
    """Base class for all asset types (JS, CSS, XML)."""

    def __init__(
        self,
        bundle: AssetsBundle,
        inline: str | None = None,
        url: str | None = None,
        filename: str | None = None,
        last_modified: float | None = None,
    ) -> None:
        self.bundle = bundle
        self.inline = inline
        self.url = url
        self._filename = filename
        self._content: str | None = None
        self._ir_attach: IrAttachment | None = None
        self._last_modified = last_modified
        if not inline and not url:
            # ``bundle`` is guarded only so the error itself cannot crash: the
            # contract is a real AssetsBundle (the sole bundle-less construction,
            # ``ScssStylesheetAsset.for_inline_compile``, always inlines).
            bundle_name = bundle.name if bundle is not None else "<no bundle>"
            raise ValueError(
                f"An asset should either be inlined or url linked, defined in bundle {bundle_name!r}"
            )

    def generate_error(self, msg: str) -> str:
        """Log and return an error message contextualized with the asset URL."""
        msg = f"{msg!r} in file {self.url!r}"
        _logger.error(msg)
        return msg

    @functools.cached_property
    def id(self) -> str:
        return str(uuid.uuid4())

    @functools.cached_property
    def unique_descriptor(self) -> str:
        return f"{self.url or self.inline},{self.last_modified}"

    @functools.cached_property
    def name(self) -> str:
        return "<inline asset>" if self.inline else self.url

    def _resolve_attachment(self) -> None:
        """Resolve a url-only asset to its backing ``ir.attachment`` record.

        No-op for inline or file-backed assets; raises ``AssetNotFoundError``
        when no attachment serves the URL.
        """
        if not (self.inline or self._filename or self._ir_attach):
            try:
                self._ir_attach = (
                    self.bundle.env["ir.attachment"]
                    .sudo()
                    ._get_serve_attachment(self.url)
                )
                self._ir_attach.ensure_one()
            except ValueError:
                raise AssetNotFoundError(f"Could not find {self.name}") from None

    @property
    def last_modified(self) -> float | int:
        if self._last_modified is None:
            # Only the expected "asset has no backing attachment" failure is
            # ignored; a real DB error must propagate, not become ``-1``.
            with suppress(AssetNotFoundError):
                self._resolve_attachment()
            if self._filename:
                # debug=assets builds assets without a build-time mtime, so each
                # render re-stats. Also covers a caller omitting ``last_modified``
                # for a file-backed asset — previously that froze the checksum on
                # ``-1`` and file edits stopped invalidating the bundle.
                with suppress(OSError):
                    self._last_modified = Path(self._filename).stat().st_mtime
            elif self._ir_attach:
                self._last_modified = self._ir_attach.write_date.replace(
                    tzinfo=UTC
                ).timestamp()
            if self._last_modified is None:
                # ``is None``, not falsy: an epoch mtime (0.0) is a real
                # timestamp and must not collapse into the sentinel.
                self._last_modified = -1
        return self._last_modified

    @property
    def content(self) -> str:
        if self._content is None:
            self._content = self._raw_source()
        return self._content

    def _raw_source(self) -> str:
        """The asset's unprocessed source: inline if present, else fetched.

        Uncached — :attr:`content` layers caching on top, and
        ``StylesheetAsset.get_source`` re-reads through this to recompile from
        the original source. ``inline`` is the empty string for file-backed
        assets, so the ``or`` falls through to the fetch when there is no body.
        """
        return self.inline or self._fetch_content()

    def _fetch_content(self) -> str:
        """Fetch content from file or database."""
        try:
            self._resolve_attachment()
            if self._filename:
                with file_open(self._filename, "rb", filter_ext=EXTENSIONS) as fp:
                    return fp.read().decode("utf-8")
            else:
                return self._ir_attach.raw.decode()
        except UnicodeDecodeError:
            raise AssetError(f"{self.name} is not utf-8 encoded.") from None
        except OSError:
            raise AssetNotFoundError(f"File {self.name} does not exist.") from None
        except AssetError:
            # Already contextualized; re-wrapping would erase the subclass.
            raise
        except ValueError as e:
            # ``file_open(filter_ext=...)`` rejecting the extension.
            raise AssetError(f"Could not get content for {self.name}.") from e

    def minify(self) -> str:
        """Return this asset's bundle-ready fragment.

        Subclasses compress the content and prepend the per-file header; the base
        implementation passes the content through untouched.
        """
        return self.content

    def with_header(self, content: str | None = None) -> str:
        if content is None:
            content = self.content
        return f"\n/* {self.name} */\n{content}"


class JavascriptAsset(WebAsset):
    """JS file asset: legacy concatenation member or native-ESM module."""

    # Lines ``with_header(minimal=False)`` emits BEFORE the file body (blank +
    # top border + 2 info lines + bottom border). ``js_with_sourcemap`` feeds it
    # to the sourcemap generator as ``start_offset``. Keep in sync with
    # ``with_header``; ``test_js_header_line_count`` guards the coupling.
    _HEADER_LINE_COUNT = 5

    @functools.cached_property
    def parsed_header(self) -> re.Match[str] | None:
        """Parsed ``@odoo-module`` header match (cached), or ``None``.

        The header is consulted at several points in the bundle lifecycle
        (native/legacy classification, import-map alias, esbuild flags); caching
        parses the file's first 500 chars once.
        """
        return _parse_odoo_module_header(self.raw_content)

    def generate_error(self, msg: str) -> str:
        msg = super().generate_error(msg)
        return f"console.error({json.dumps(msg)});"

    @functools.cached_property
    def is_native(self) -> bool:
        """Whether this file uses ``@odoo-module native`` (browser-native ESM)."""
        header = self.parsed_header
        return bool(header and header["native"])

    @functools.cached_property
    def module_path(self) -> str:
        """The ``@module/path`` identifier (e.g. ``@web/core/registry``).

        Cached — a pure function of the immutable ``self.url``, read several
        times per module (import map, esbuild entry, both bridge builders).
        """
        return url_to_module_path(self.url)

    @property
    def raw_content(self) -> str:
        """The file's source (cached by ``WebAsset``).

        Public alias of :attr:`content` for call sites that read a JS asset's
        source explicitly (``ir_qweb``, the bridge builders). For JS the two are
        identical — there is no transpilation step.
        """
        return super().content

    def minify(self) -> str:
        content = self.content
        # rjsmin (1.2.5) corrupts NESTED template literals (whitespace inside a
        # template-in-``${}`` collapses). A nested literal REQUIRES an
        # interpolation, so a file with backticks but no ``${`` is safe — minify
        # it in-process. Only ``${``-bearing backtick files go to esbuild (a
        # conservative textual superset). On esbuild failure the file ships
        # unminified, as before.
        if "`" not in content or "${" not in content:
            return self.with_header(rjsmin(content, keep_bang_comments=True))
        minified = minify_js(content, label=self.url or self.name)
        return self.with_header(minified if minified is not None else content)

    def _fetch_content(self) -> str:
        try:
            return super()._fetch_content()
        except AssetError as e:
            return self.generate_error(str(e))

    def with_header(self, content: str | None = None, minimal: bool = True) -> str:
        if minimal:
            return super().with_header(content)

        # Verbose header — _HEADER_LINE_COUNT (5) lines before the body,
        # consumed by js_with_sourcemap as the sourcemap offset:
        #   <blank>
        #   /**************************
        #   *  Filepath: <asset_url>  *
        #   *  Lines: 42              *
        #   **************************/
        line_count = content.count("\n")
        lines = [
            f"Filepath: {self.url}",
            f"Lines: {line_count}",
        ]
        length = max(map(len, lines))
        return "\n".join(
            [
                "",
                "/" + "*" * (length + 5),
                *(f"*  {line:<{length}}  *" for line in lines),
                "*" * (length + 5) + "/",
                content,
            ]
        )


class XMLAsset(WebAsset):
    """OWL template (.xml) asset, consumed as parsed elements by ``xml()``."""

    @functools.cached_property
    def _parsed_root(self) -> etree._Element:
        """Parse the asset's XML source once; cache the root element.

        ``template_elements`` (the only production consumer) derives from this
        single parse, avoiding a parse/serialize/parse round-trip per file.
        """
        try:
            raw = self._raw_source()
        except AssetError as e:
            raise self._error(str(e)) from e
        parser = etree.XMLParser(
            ns_clean=True, remove_comments=True, resolve_entities=False
        )
        try:
            return etree.fromstring(raw.encode("utf-8"), parser=parser)
        except etree.XMLSyntaxError as e:
            raise self._error(f"Invalid XML template: {e.msg}") from e

    @functools.cached_property
    def template_elements(self) -> list[etree._Element]:
        """Return the individual template elements parsed from this asset.

        For a ``<templates>``/``<template>``/``<odoo>`` wrapper the children are
        the templates; any other root tag is itself a single template element.
        """
        root = self._parsed_root
        if root.tag in ("templates", "template", "odoo"):
            # Keep elements only: the parser strips comments but not processing
            # instructions, and a PI reaching ``xml()`` aborts the bundle with a
            # misleading "Template name is missing."
            return [el for el in root if isinstance(el.tag, str)]
        return [root]

    def _error(self, msg: str) -> XMLAssetError:
        """Log and build the contextualized error; the caller raises it.

        Unlike ``JavascriptAsset.generate_error`` (which returns an embedded JS
        stub), XML template problems abort the whole bundle — keeping the
        ``raise`` at the call site makes that control flow visible.
        """
        return XMLAssetError(super().generate_error(msg))


class StylesheetAsset(WebAsset):
    """Plain CSS asset with relative-URL rewriting and regex minification."""

    # Both rewrite patterns consume the WHOLE quoted argument — opening quote,
    # body, and closing ``(?P=q)`` — and their replacements re-emit the closing
    # quote. Consuming only the opening quote desynchronizes
    # ``_rewrite_css_outside_strings``'s quote pairing: the scanner then reads
    # ``") format("`` as a string literal and swallows every subsequent
    # ``url(`` token of a multi-url ``src:`` list (or the next ``@import``), so
    # only the first URL of a ``@font-face`` ``src:`` was ever rewritten and
    # bundle web fonts 404'd against ``/web/assets/<unique>/``.
    rx_import = re.compile(
        r"""@import\s+(?P<q>'|")(?!'|"|/|https?://)(?P<path>[^'"]*)(?P=q)"""
    )
    # ``rx_url`` matches ``url(`` and the optional opening quote, capturing the
    # relative body. Capturing it lets us prefix ``web_dir/`` and collapse the
    # ``<dir>/../<seg>`` the concatenation produces. Without the collapse the
    # emitted URL wouldn't match ``<link rel="preload" href="…">`` byte-for-byte
    # and the browser deems the preload unused — see
    # knowledge/.../2026-04-19-esm-import-map-conflict-investigation.md §10.2.
    # A quoted url whose body contains a quote-stopper (space, ``'``, ``"``,
    # ``)``) no longer half-matches: ``(?P=q)`` fails and the url is left
    # untouched (before, the body was truncated at the stopper and mangled).
    rx_url = re.compile(
        r"""(?<!")url\s*\(\s*(?P<q>['"]|)(?!['"]|/|https?://|data:|\#\{str)(?P<body>[^'")\s]*)(?P=q)""",
    )
    rx_charset = re.compile(r'(@charset "[^"]+";)')
    # The two CSS spans minification must NOT reach into — comments and string
    # literals — tokenized by the shared ``_CSS_STRING_OR_COMMENT``. Reused here
    # so the masking minifier and ``_rewrite_css_outside_strings`` share one
    # tokenizer and cannot drift on what they treat as opaque.
    _CSS_TOKEN_RE = _CSS_STRING_OR_COMMENT

    def __init__(
        self, *args: Any, rtl: bool = False, autoprefix: bool = False, **kw: Any
    ) -> None:
        self.rtl = rtl
        self.autoprefix = autoprefix
        # Per-asset fetch/rewrite errors, recorded by ``_fetch_content`` and
        # harvested into the bundle's ``css_errors`` by ``preprocess_css``.
        # StylesheetAsset-only (not WebAsset): "record and degrade to empty
        # output" is the *stylesheet* recovery policy — JS degrades via a
        # console.error stub, XML treats a content error as fatal.
        self.errors: list[str] = []
        super().__init__(*args, **kw)

    @functools.cached_property
    def unique_descriptor(self) -> str:
        direction = (self.rtl and "rtl") or "ltr"
        autoprefixed = (self.autoprefix and "autoprefixed") or ""
        return (
            f"{self.url or self.inline},{self.last_modified},{direction},{autoprefixed}"
        )

    def _fetch_content(self) -> str:
        try:
            content = super()._fetch_content()
            # ``self.url`` is a forward-slash web path: resolve its directory
            # with posixpath, NOT pathlib.Path (``WindowsPath.parent`` would emit
            # backslashes that leak into the rewritten URLs).
            web_dir = posixpath.dirname(self.url)

            def _rewrite_import(match: re.Match[str]) -> str:
                # Function replacement (like ``_rewrite_url``): never splice
                # ``web_dir`` into a regex replacement TEMPLATE, where a
                # backslash would raise ``re.PatternError`` past this handler.
                q = match.group("q")
                return f"@import {q}{web_dir}/{match.group('path')}{q}"

            if self.rx_import:
                content = _rewrite_css_outside_strings(
                    self.rx_import, _rewrite_import, content
                )

            def _rewrite_url(match: re.Match[str]) -> str:
                # Prefix the bundled URL with ``web_dir`` then collapse
                # ``<dir>/../`` segments so the rewritten ``url(…)`` is
                # byte-identical to a ``<link rel="preload">`` URL. An empty body
                # (``url()``) is preserved by the dedicated branch below.
                # Applied via ``_rewrite_css_outside_strings``, so a ``url(...)``
                # inside a ``content: "…"`` value or comment is skipped, while a
                # real ``url("x")`` (matched at the ``url(`` token) is rewritten.
                q = match.group("q")
                body = match.group("body")
                if not body:
                    return f"url({q}{web_dir}/{q}"
                normalised = posixpath.normpath(f"{web_dir}/{body}")
                return f"url({q}{normalised}{q}"

            content = _rewrite_css_outside_strings(self.rx_url, _rewrite_url, content)

            # remove charset declarations, we only support utf-8
            return self.rx_charset.sub("", content)
        except AssetError as e:
            self.errors.append(str(e))
            return ""

    def get_source(self) -> str:
        # ``odoo-split:`` namespaces the marker against legitimate CSS loud
        # comments Sass preserves (see ``CssPipeline.rx_css_split``).
        # ``_raw_source`` (not ``content``): the compile input must be re-read
        # from the original source, bypassing the ``_content`` cache that
        # ``preprocess`` later overwrites with the compiled fragment.
        return f"/*! odoo-split:{self.id} */\n{self._raw_source()}"

    @classmethod
    def _minify_css_body(cls, content: str) -> str:
        """Minify CSS text, leaving string literals and legal comments intact.

        Strategy: mask the spans minification must not touch — string literals
        and ``/*! … */`` legal comments (license headers) — behind inert
        NUL-delimited placeholders, drop ordinary comments, run the legacy
        whitespace-collapse + brace-tighten, then restore the masked spans. The
        placeholders carry no whitespace or braces, so the structural output is
        byte-identical to the legacy pipeline; the only change is that string /
        legal-comment interiors are no longer corrupted (the old string-unaware
        regexes lost a space in ``content: "a  b"``).

        :attr:`_CSS_TOKEN_RE`'s alternation order makes the masking correct
        across interleaving: a ``"`` inside a comment is consumed by the comment
        arm, and a ``/*`` inside a string by the string arm.

        A pre-existing ``/*# sourceMappingURL=… */`` needs no separate pass: it
        is an ordinary block comment the mask step drops, while a
        ``sourceMappingURL`` inside a ``content: "…"`` value survives (the old
        whole-text ``rx_sourceMap.sub`` reached into strings).

        Header-less for unit-testing against the legacy pipeline; :meth:`minify`
        adds the header.
        """
        # NUL is invalid in CSS (spec replaces U+0000 with U+FFFD). Strip it so
        # source text can't collide with the NUL-delimited placeholders below: a
        # raw ``\x00<digits>\x00`` would be caught by the restore regex and index
        # into ``protected`` — an IndexError that kills the whole CSS compile.
        content = content.replace("\x00", "")

        protected: list[str] = []

        def _mask(match: re.Match[str]) -> str:
            token = match.group()
            if token[0] in "\"'" or token.startswith("/*!"):
                protected.append(token)
                return f"\x00{len(protected) - 1}\x00"
            return ""  # ordinary comment — dropped

        masked = cls._CSS_TOKEN_RE.sub(_mask, content)
        masked = re.sub(r"\s+", " ", masked)
        masked = re.sub(r" *([{}]) *", r"\1", masked)
        # Restore via a function replacement so backslashes inside a string
        # literal are not reinterpreted as regex escapes.
        return re.sub(r"\x00(\d+)\x00", lambda m: protected[int(m.group(1))], masked)

    def minify(self) -> str:
        # In debug, ``css_with_sourcemap`` rebuilds the bundle from each asset's
        # ``content`` and the minified join is consumed only for @import
        # extraction (unminified content serves equally well), so skip the regex
        # passes — mirroring ``ScssStylesheetAsset.minify``. Production still
        # minifies: there the join IS the ``.min.css`` body.
        if self.bundle.is_debug_assets:
            return self.with_header(self.content)
        return self.with_header(self._minify_css_body(self.content))


class PreprocessedCSS(StylesheetAsset):
    """Base for stylesheet dialects compiled through an external CLI."""

    rx_import = None

    # Largest bundles take tens of seconds on the CLI fallback path; generous,
    # but a hung compiler must not pin a worker.
    _COMPILE_TIMEOUT_S: int = 180

    def get_command(self) -> list[str]:
        """Return the compiler argv reading source on stdin."""
        raise NotImplementedError

    def compile(self, source: str) -> str:
        """Compile ``source`` through :meth:`get_command`; raise ``CompileError``."""
        return _run_cli_pipe(self.get_command(), source, self._COMPILE_TIMEOUT_S)


class ScssStylesheetAsset(PreprocessedCSS):
    """Compile SCSS (.scss) using Dart Sass (embedded protocol or CLI)."""

    @classmethod
    def for_inline_compile(
        cls, source: str = "// inline compile"
    ) -> ScssStylesheetAsset:
        """Build a bundle-less asset whose sole purpose is :meth:`compile`.

        The document-layout preview (``base_document_layout``) compiles wizard
        SCSS outside any bundle; this is the ONE sanctioned bundle-less
        construction. ``bundle=None`` selects the production ``compressed``
        output style (see :attr:`output_style`).

        :param source: placeholder inline content satisfying the inline-or-url
            invariant; :meth:`compile` takes the real SCSS explicitly.
        """
        return cls(None, inline=source)

    # Process-wide one-shot guard for the embedded-Sass → CLI fallback warning
    # (see :meth:`_warn_embedded_fallback`). A class attribute so flipping it
    # needs no ``global``.
    _embedded_fallback_warned = False

    @classmethod
    def _warn_embedded_fallback(cls, exc: Exception) -> None:
        """Surface the embedded-Sass → CLI degrade: WARNING once, then DEBUG.

        A broken sass-embedded install otherwise logs the much slower
        per-compile CLI fallback only at DEBUG, hiding the regression. Later
        fallbacks stay at DEBUG so a persistent failure doesn't flood the log.
        """
        if cls._embedded_fallback_warned:
            _logger.debug("Dart Sass embedded unavailable, using CLI", exc_info=exc)
            return
        ScssStylesheetAsset._embedded_fallback_warned = True
        _logger.warning(
            "Embedded Dart Sass unavailable (%s); falling back to the Dart Sass "
            "CLI for every SCSS compile. The CLI path is markedly slower (a "
            "per-bundle subprocess, up to %ss) — install/repair sass-embedded to "
            "restore the fast path. This warning fires once per process.",
            exc,
            cls._COMPILE_TIMEOUT_S,
        )

    @property
    def bootstrap_path(self) -> str:
        return file_path("web/static/lib/bootstrap/scss")

    @property
    def output_style(self) -> str:
        """Use compressed output in production for AST-aware minification."""
        return (
            "expanded" if self.bundle and self.bundle.is_debug_assets else "compressed"
        )

    @property
    def _sass_syntax(self) -> str:
        """Sass syntax identifier for this asset type."""
        return "scss"

    def minify(self) -> str:
        """Dart Sass output needs no regex pass.

        Production output is already ``compressed``; in debug the join this
        feeds is consumed only for ``@import`` extraction, so regex-minifying
        the expanded output would be wasted work.
        """
        return self.with_header()

    def compile(self, source: str) -> str:
        """Compile SCSS: embedded Dart Sass -> Dart Sass CLI."""
        import odoo.addons

        # Try 1: Embedded Sass Protocol (fast, custom importers)
        try:
            # ``SassCompileError`` is imported at module level; only the
            # embedded-protocol-specific symbols are imported lazily here.
            from odoo.tools.sass_embedded import (
                OdooSassImporter,
                get_sass_compiler,
            )

            compiler = get_sass_compiler()
            profiler.force_hook()
            return compiler.compile_string(
                source,
                syntax=self._sass_syntax,
                importers=[OdooSassImporter(self.bootstrap_path)],
                load_paths=[self.bootstrap_path, *odoo.addons.__path__],
                style=self.output_style,
                quiet_deps=True,
            )
        except SassCompileError:
            raise
        except SassNotFoundError:
            # Dart Sass is required — a missing binary is a deployment
            # misconfiguration, not a transient embedded-protocol failure. Fail
            # loudly rather than degrade to the CLI (which needs the same binary).
            raise
        except Exception as exc:
            # A broken/unavailable embedded compiler (dead subprocess, …) — NOT
            # a real SCSS error (SassCompileError, re-raised above) — degrades to
            # the CLI. Warned once (see :meth:`_warn_embedded_fallback`).
            self._warn_embedded_fallback(exc)
            # Close the singleton to reap any zombie process.
            from odoo.tools.sass_embedded import close_sass_compiler

            close_sass_compiler()

        # Try 2: Dart Sass CLI (no custom importers, uses --load-path)
        return super().compile(source)

    def get_command(self) -> list[str]:
        """Build the Dart Sass CLI command."""
        import odoo.addons

        sass = find_sass()
        if sass is None:
            raise SassNotFoundError(
                "Dart Sass not found. It is a required dependency of this fork: "
                "run `npm install` in the Odoo root (declared in package.json) "
                "or install a `sass` binary on PATH."
            )
        load_paths = [self.bootstrap_path, *odoo.addons.__path__]
        cmd = [
            sass,
            "--stdin",
            "--no-source-map",
            "--style",
            self.output_style,
            "--quiet-deps",
            "--silence-deprecation=import",
            "--silence-deprecation=global-builtin",
            "--silence-deprecation=if-function",
            "--silence-deprecation=duplicate-var-flags",
            "--silence-deprecation=color-functions",
        ]
        for path in load_paths:
            cmd.extend(["--load-path", path])
        return cmd
