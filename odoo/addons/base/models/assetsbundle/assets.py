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
    has_nested_template_literal,
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
    from .bundle import AssetsBundle
    from odoo.addons.base.models.ir_attachment import IrAttachment
from .common import (
    _CSS_STRING_OR_COMMENT,
    _SCSS_STRING_OR_COMMENT,
    AssetError,
    AssetNotFoundError,
    XMLAssetError,
    _logger,
    _rewrite_css_outside_strings,
    _run_cli_pipe,
)


class WebAsset:
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
            bundle_name = bundle.name if bundle is not None else "<no bundle>"
            raise ValueError(
                f"An asset should either be inlined or url linked, defined in bundle {bundle_name!r}"
            )

    def generate_error(self, msg: str) -> str:
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
            with suppress(AssetNotFoundError):
                self._resolve_attachment()
            if self._filename:
                with suppress(OSError):
                    self._last_modified = Path(self._filename).stat().st_mtime
            elif self._ir_attach:
                self._last_modified = self._ir_attach.write_date.replace(
                    tzinfo=UTC
                ).timestamp()
            if self._last_modified is None:
                self._last_modified = -1
        return self._last_modified

    @property
    def content(self) -> str:
        if self._content is None:
            self._content = self._raw_source()
        return self._content

    def _raw_source(self) -> str:
        return self.inline or self._fetch_content()

    def _fetch_content(self) -> str:
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
            raise
        except ValueError as e:
            raise AssetError(f"Could not get content for {self.name}.") from e

    def minify(self) -> str:
        return self.content

    def with_header(self, content: str | None = None) -> str:
        if content is None:
            content = self.content
        return f"\n/* {self.name} */\n{content}"


class JavascriptAsset(WebAsset):
    _HEADER_LINE_COUNT = 5

    @functools.cached_property
    def parsed_header(self) -> re.Match[str] | None:
        return _parse_odoo_module_header(self.raw_content)

    def generate_error(self, msg: str) -> str:
        msg = super().generate_error(msg)
        return f"console.error({json.dumps(msg)});"

    @functools.cached_property
    def is_native(self) -> bool:
        header = self.parsed_header
        return bool(header and header["native"])

    @functools.cached_property
    def module_path(self) -> str:
        return url_to_module_path(self.url)

    @property
    def raw_content(self) -> str:
        return super().content

    def minify(self) -> str:
        content = self.content
        if not has_nested_template_literal(content):
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
    @property
    def _parsed_root(self) -> etree._Element:
        result = self._parse_result
        if isinstance(result, XMLAssetError):
            raise result
        return result

    @functools.cached_property
    def _parse_result(self) -> etree._Element | XMLAssetError:
        try:
            raw = self._raw_source()
        except AssetError as e:
            return self._error(str(e))
        parser = etree.XMLParser(
            ns_clean=True, remove_comments=True, resolve_entities=False
        )
        try:
            return etree.fromstring(raw.encode("utf-8"), parser=parser)
        except etree.XMLSyntaxError as e:
            return self._error(f"Invalid XML template: {e.msg}")

    @functools.cached_property
    def template_elements(self) -> list[etree._Element]:
        root = self._parsed_root
        if root.tag in ("templates", "template", "odoo"):
            return [el for el in root if isinstance(el.tag, str)]
        return [root]

    def _error(self, msg: str) -> XMLAssetError:
        return XMLAssetError(super().generate_error(msg))


class StylesheetAsset(WebAsset):
    rx_import = re.compile(
        r"""@import\s+(?P<q>'|")(?!'|"|/|https?://)(?P<path>[^'"]*)(?P=q)"""
    )
    rx_url = re.compile(
        r"""url\s*\(\s*(?P<q>['"]|)"""
        r"""(?!['"]|/|https?://|data:|\#\{str|\#(?!\{))"""
        r"""(?P<body>[^'")\s]*)(?P=q)""",
    )
    """Match a ``url(…)`` whose body is a *relative path* needing rewriting.

    Carried no leading ``(?<!")`` guard since string protection moved into
    :func:`_rewrite_css_outside_strings`. That lookbehind used to keep the
    rewrite out of ``content: "…url(x)…"``; the scanner now consumes string
    literals as opaque spans, so the only thing it could still do was refuse a
    genuine ``url()`` that happened to abut a closing quote
    (``background:"x"url(y.png)``), leaving that reference relative to the
    bundle URL — a silent 404.

    The lookahead skips what must be left alone:

    * an already-absolute or protocol-relative href, and a ``data:`` payload;
    * ``#{str…}`` — an interpolation calling ``str-replace``/``str-slice``,
      whose arguments carry ``)`` and spaces that ``body`` cannot span;
    * ``#`` NOT followed by ``{`` — a same-document reference
      (``clip-path: url(#clip)``, ``mask: url(#m)``, ``behavior:
      url(#default#VML)``). Prefixing one with the stylesheet's directory
      resolves it to nothing and silently drops the effect.

    ``#{`` itself must still MATCH: the rewrite runs on Sass *source*, and the
    common shape is a path whose leading segment is interpolated
    (``url("#{$lato-font-path}/Lato-Reg-webfont.eot")``, where
    ``$lato-font-path`` is ``"./lato"``). Skipping those leaves a URL relative
    to the *bundle* URL, so every Lato/Google web font 404s.
    """
    rx_charset = re.compile(r'(@charset "[^"]+";)')
    _CSS_TOKEN_RE = _CSS_STRING_OR_COMMENT
    _SOURCE_TOKEN_RE = _CSS_STRING_OR_COMMENT
    _IDENT_CHAR = re.compile(r"[\w-]")
    """Characters that can continue an identifier, a number or a dimension.

    A CSS comment is not whitespace, so dropping one usually joins nothing —
    ``.a/*x*/.b`` really is ``.a.b``. But between two of THESE characters the
    comment is the only thing keeping two tokens apart, and deleting it fuses
    them: ``@media/*c*/screen`` became the single at-keyword ``@mediascreen``
    and the browser dropped the whole block; ``1px/*c*/2px`` became the invalid
    dimension ``1px2px``. Only that case substitutes a space.
    """

    def __init__(
        self, *args: Any, rtl: bool = False, autoprefix: bool = False, **kw: Any
    ) -> None:
        self.rtl = rtl
        self.autoprefix = autoprefix
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
            web_dir = posixpath.dirname(self.url)

            def _rewrite_import(match: re.Match[str]) -> str:
                q = match.group("q")
                return f"@import {q}{web_dir}/{match.group('path')}{q}"

            if self.rx_import:
                content = _rewrite_css_outside_strings(
                    self.rx_import, _rewrite_import, content, self._SOURCE_TOKEN_RE
                )

            def _rewrite_url(match: re.Match[str]) -> str:
                q = match.group("q")
                body = match.group("body")
                if not body:
                    return f"url({q}{web_dir}/{q}"
                normalised = posixpath.normpath(f"{web_dir}/{body}")
                return f"url({q}{normalised}{q}"

            content = _rewrite_css_outside_strings(
                self.rx_url, _rewrite_url, content, self._SOURCE_TOKEN_RE
            )

            return self.rx_charset.sub("", content)
        except AssetError as e:
            self.errors.append(str(e))
            return ""

    def get_source(self) -> str:
        return f"/*! odoo-split:{self.id} */\n{self._raw_source()}"

    @classmethod
    def _minify_css_body(cls, content: str) -> str:
        content = content.replace("\x00", "")

        protected: list[str] = []

        def _mask(match: re.Match[str]) -> str:
            token = match.group()
            if token[0] in "\"'" or token.startswith("/*!"):
                protected.append(token)
                return f"\x00{len(protected) - 1}\x00"
            before = content[match.start() - 1 : match.start()]
            after = content[match.end() : match.end() + 1]
            if cls._IDENT_CHAR.match(before) and cls._IDENT_CHAR.match(after):
                return " "
            return ""

        masked = cls._CSS_TOKEN_RE.sub(_mask, content)
        masked = re.sub(r"\s+", " ", masked)
        masked = re.sub(r" *([{}]) *", r"\1", masked)
        return re.sub(r"\x00(\d+)\x00", lambda m: protected[int(m.group(1))], masked)

    def minify(self) -> str:
        if self.bundle.is_debug_assets:
            return self.with_header(self.content)
        return self.with_header(self._minify_css_body(self.content))


class PreprocessedCSS(StylesheetAsset):
    rx_import = None
    _SOURCE_TOKEN_RE = _SCSS_STRING_OR_COMMENT

    _COMPILE_TIMEOUT_S: int = 180

    def get_command(self) -> list[str]:
        raise NotImplementedError

    def compile(self, source: str) -> str:
        return _run_cli_pipe(self.get_command(), source, self._COMPILE_TIMEOUT_S)


class ScssStylesheetAsset(PreprocessedCSS):
    @classmethod
    def for_inline_compile(
        cls, source: str = "// inline compile"
    ) -> ScssStylesheetAsset:
        return cls(None, inline=source)

    _embedded_fallback_warned = False

    @classmethod
    def _warn_embedded_fallback(cls, exc: Exception) -> None:
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
        return (
            "expanded" if self.bundle and self.bundle.is_debug_assets else "compressed"
        )

    _sass_syntax = "scss"
    """Dart Sass syntax identifier; see :class:`SassStylesheetAsset`."""

    def minify(self) -> str:
        return self.with_header()

    def compile(self, source: str) -> str:
        import odoo.addons

        try:
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
            raise
        except Exception as exc:
            self._warn_embedded_fallback(exc)
            from odoo.tools.sass_embedded import close_sass_compiler

            close_sass_compiler()

        return super().compile(source)

    def get_command(self) -> list[str]:
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
            "--indented" if self._sass_syntax == "indented" else "--no-indented",
            "--no-source-map",
            "--no-charset",
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


class SassStylesheetAsset(ScssStylesheetAsset):
    _sass_syntax = "indented"
