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
    return file_path("base/data/rtlcss.json")


class CssPipeline:
    rx_preprocess_imports = re.compile(
        r"""@import\s*['"](?P<ref>[^'"]+)['"](?P<tail>[^;{]*;?)"""
    )
    rx_css_split = re.compile(r"/\*! odoo-split:([a-f0-9-]+) \*/")
    rx_css_import = re.compile(r"(@import[^;{]+;?)")

    _RTLCSS_TIMEOUT_S: int = 60

    _CSS_ERROR_HEADER = "\n\n/* ## CSS error message ##*/"

    def __init__(self, bundle: AssetsBundle) -> None:
        self._bundle = bundle
        self._rendered_assets: list[StylesheetAsset] = []

    def preprocess(self) -> str:
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
        import_rules: list[str] = []

        def _hoist(match: re.Match) -> str:
            import_rules.append(match.group(0))
            return ""

        remainder = _rewrite_css_outside_strings(self.rx_css_import, _hoist, css)
        return import_rules, remainder

    def compile_css(self, compiler: Callable[[str], str], source: str) -> str:
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
    _COMPILED_CACHE_SIZE = 32
    _compiled_cache_lock = threading.Lock()

    @classmethod
    def _memoized_transform(
        cls, key: tuple, source: str, transform: Callable[[str], str]
    ) -> str:
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
        asset = getattr(compiler, "__self__", None)
        key = ("compile", type(asset).__name__, getattr(asset, "output_style", None))
        return cls._memoized_transform(key, source, lambda src: compiler(src).strip())

    _RX_APPEARANCE = re.compile(
        r"(?<=[{;\s])appearance\s*:\s*(?P<value>[\w-]+)(?P<important>\s*!important)?"
    )

    @classmethod
    def _autoprefix_css(cls, source: str) -> str:

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
