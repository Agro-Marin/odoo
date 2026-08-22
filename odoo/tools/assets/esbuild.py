import contextlib
import functools
import glob
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import odoo
from odoo.libs.asset_log import get_asset_logger, log_event
from odoo.tools.json import scriptsafe as json

_esbuild_log = get_asset_logger("esbuild")

EXTERNAL_SPECIFIER_PREFIX = "@odoo/"

# External-lib specifiers that are merely another name for a file a bundle can
# itself carry.  Registering one in ``odoo.loader.modules`` is legitimate only
# when the bundle provides the aliased module, never unconditionally: the three
# below are the HOOT test framework, and a page that registers them has loaded
# the test framework.  Both renderers consult this table -- the esbuild entry in
# ``_esbuild_entry_lines`` and the per-file fallback in
# ``IrQweb._get_esm_nodes_debug`` -- so they cannot drift apart.
EXTERNAL_LIB_ALIASES = {
    "@odoo/hoot": "@web/../lib/hoot/hoot",
    "@odoo/hoot-dom": "@web/../lib/hoot-dom/hoot-dom",
    "@odoo/hoot-mock": "@web/../lib/hoot/hoot-mock",
}


class EsbuildResult(NamedTuple):
    code: str
    metafile: str | None
    sourcemap: str | None


@functools.cache
def _find_esbuild() -> str | None:
    odoo_root = Path(odoo.__path__[0]).parent
    return shutil.which("esbuild") or shutil.which(
        "esbuild",
        path=str(odoo_root / "node_modules" / ".bin"),
    )


_TEMPLATE_LITERAL_TOKENS = re.compile(r"\\.|`|\$\{|\}", re.DOTALL)


def has_nested_template_literal(source: str) -> bool:
    if "`" not in source or "${" not in source:
        return False
    stack: list[str] = []
    for match in _TEMPLATE_LITERAL_TOKENS.finditer(source):
        token = match.group()
        if token[0] == "\\":
            continue
        if token == "`":
            if stack and stack[-1] == "tpl":
                stack.pop()
            elif "sub" in stack:
                return True
            else:
                stack.append("tpl")
        elif token == "${":
            if stack and stack[-1] == "tpl":
                stack.append("sub")
        elif stack and stack[-1] == "sub":
            stack.pop()
    return False


def minify_js(
    source: str, *, label: str = "<asset>", timeout_s: int = 60
) -> str | None:
    esbuild_bin = _find_esbuild()
    if not esbuild_bin:
        log_event(_esbuild_log, logging.WARNING, "minify_no_binary", asset=label)
        return None
    argv = [
        esbuild_bin,
        "--minify",
        "--loader=js",
        f"--target={EsbuildCompiler._ESBUILD_TARGET}",
        "--charset=utf8",
        "--legal-comments=inline",
        "--log-level=error",
    ]
    t0 = time.monotonic()
    try:
        result = subprocess.run(
            argv,
            input=source,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        log_event(
            _esbuild_log,
            logging.WARNING,
            "minify_timeout",
            asset=label,
            timeout_s=timeout_s,
        )
        return None
    if result.returncode != 0:
        log_event(
            _esbuild_log,
            logging.WARNING,
            "minify_failed",
            asset=label,
            exit=result.returncode,
        )
        _esbuild_log.warning("esbuild minify stderr for %s:\n%s", label, result.stderr)
        return None
    log_event(
        _esbuild_log,
        logging.DEBUG,
        "minify",
        asset=label,
        in_kb=f"{len(source) / 1024:.0f}",
        out_kb=f"{len(result.stdout) / 1024:.0f}",
        elapsed=f"{time.monotonic() - t0:.3f}",
    )
    return result.stdout.strip()


class EsbuildCompiler:
    def __init__(
        self,
        name: str,
        native_modules: list,
        javascripts: list | tuple = (),
        *,
        import_map_included: bool = False,
        skip_legacy_test_imports: bool = False,
        standalone: bool = False,
        addon_flags_provider: Callable[[Path], tuple[list[str], list[str]]]
        | None = None,
    ) -> None:
        self.name = name
        self.native_modules = list(native_modules)
        self.javascripts = list(javascripts)
        self._import_map_included = import_map_included
        self._skip_legacy_test_imports = skip_legacy_test_imports
        self._standalone = standalone
        self._addon_flags_provider = (
            addon_flags_provider or self._get_esbuild_addon_flags
        )
        self._last_metafile: str | None = None
        self._last_sourcemap: str | None = None

    _esbuild_addon_scan_cache: tuple | None = None

    @classmethod
    def invalidate_addon_scan_cache(cls) -> None:
        cls._esbuild_addon_scan_cache = None

    @classmethod
    def resolves_specifier(cls, spec: str) -> bool:
        from odoo.tools.assets.esm_registry import external_bare_specifiers

        return (
            spec.startswith(EXTERNAL_SPECIFIER_PREFIX)
            or spec in external_bare_specifiers()
            or spec in cls._LIB_CANDIDATES
        )

    _LIB_CANDIDATES: dict[str, tuple[str, ...]] = {
        "@odoo/hoot-dom": ("web", "static", "lib", "hoot-dom", "hoot-dom.js"),
        "@popperjs/core": (
            "web",
            "static",
            "src",
            "libs",
            "popper_compat.js",
        ),
        "@odoo/o-spreadsheet": (
            "spreadsheet",
            "static",
            "src",
            "o_spreadsheet",
            "o_spreadsheet.js",
        ),
    }

    @classmethod
    def _get_esbuild_addon_flags(cls, odoo_root: Path) -> tuple[list[str], list[str]]:
        from odoo.addons import __path__ as _addon_paths

        cache_key = tuple(_addon_paths)
        cached = cls._esbuild_addon_scan_cache
        if cached and cached[0] == cache_key:
            return list(cached[1]), list(cached[2])

        alias_flags: list[str] = []
        test_external_flags: list[str] = []
        seen_addons: set[str] = set()
        for addon_dir in _addon_paths:
            addon_dir = Path(addon_dir)
            if not addon_dir.is_dir():
                continue
            for entry in addon_dir.iterdir():
                name = entry.name
                if name in seen_addons or not entry.is_dir():
                    continue
                seen_addons.add(name)
                static_src = entry / "static" / "src"
                if static_src.is_dir():
                    rel = os.path.relpath(static_src, odoo_root)
                    alias_flags.append(f"--alias:@{name}=./{rel}")
                if (entry / "static" / "tests").is_dir():
                    test_external_flags.append(f"--external:@{name}/../tests/*")
                    rel_tests = os.path.relpath(
                        entry / "static" / "tests",
                        odoo_root,
                    )
                    test_external_flags.append(f"--external:./{rel_tests}/*")

        for alias_name, path_parts in cls._LIB_CANDIDATES.items():
            for addon_dir in _addon_paths:
                candidate = Path(addon_dir).joinpath(*path_parts)
                if candidate.exists():
                    rel = os.path.relpath(candidate, odoo_root)
                    alias_flags.append(f"--alias:{alias_name}=./{rel}")
                    break

        cls._esbuild_addon_scan_cache = (cache_key, alias_flags, test_external_flags)
        log_event(
            _esbuild_log,
            logging.DEBUG,
            "addon_scan_cached",
            aliases=len(alias_flags),
            test_externals=len(test_external_flags),
        )
        return list(alias_flags), list(test_external_flags)

    _ESBUILD_TIMEOUT_S: int = 30
    _ESBUILD_TARGET: str = "es2023"
    _ESBUILD_TARGET_TOKEN_RE = re.compile(r"[a-z]+\d*(?:\.\d+)*")
    _ESBUILD_SOURCE_MAPS: str = ""
    _ESBUILD_SOURCE_MAP_MODES: frozenset = frozenset(
        {
            "",
            "linked",
            "external",
            "inline",
        }
    )

    def compile(
        self,
        timeout_s: int | None = None,
        target: str | None = None,
        source_maps: str | None = None,
        dynamic_child_specs: frozenset[str] | None = None,
        secondary_parent_stubs: dict[str, str] | None = None,
    ) -> EsbuildResult:
        from odoo.tools.assets.esm_registry import external_bare_specifiers

        timeout_s, target, source_maps = self._esbuild_resolve_opts(
            timeout_s, target, source_maps
        )
        if not self.native_modules:
            log_event(
                _esbuild_log,
                logging.DEBUG,
                "skip",
                bundle=self.name,
                reason="no_native_modules",
            )
            return EsbuildResult("", None, None)

        if self._import_map_included:
            log_event(
                _esbuild_log,
                logging.DEBUG,
                "skip",
                bundle=self.name,
                reason="import_map_included",
            )
            return EsbuildResult("", None, None)

        _t0 = time.monotonic()

        odoo_root = Path(odoo.__path__[0]).parent
        esbuild = _find_esbuild()
        if not esbuild:
            raise FileNotFoundError(
                "esbuild is required for native ESM bundling. "
                "Run 'npm install' in the Odoo root directory."
            )

        entry_lines = self._esbuild_entry_lines(odoo_root)
        entry_text = "\n".join(entry_lines)
        entry_bytes = len(entry_text.encode("utf-8"))

        alias_flags, external_flags = self._esbuild_flags(
            odoo_root, dynamic_child_specs
        )

        tmp_dir = tempfile.mkdtemp(prefix=f"odoo-esbuild-{self.name}-")
        out_path = str(Path(tmp_dir) / "bundle.out.js")
        metafile_path = str(Path(tmp_dir) / "bundle.meta.json")

        alias_flags = self._esbuild_stub_aliases(
            list(alias_flags), secondary_parent_stubs, tmp_dir, odoo_root
        )

        log_event(
            _esbuild_log,
            logging.DEBUG,
            "invoke",
            bundle=self.name,
            entries=len(entry_lines),
            entry_bytes=entry_bytes,
            aliases=len(alias_flags),
            externals=len(external_flags) + 1,
            tmp=tmp_dir,
        )
        sourcemap_flags = [f"--sourcemap={source_maps}"] if source_maps else []
        sourcemap_path = f"{out_path}.map"
        argv = [
            esbuild,
            "--bundle",
            "--format=esm",
            "--minify",
            "--keep-names",
            f"--external:{EXTERNAL_SPECIFIER_PREFIX}*",
            "--external:/web/static/lib/*",
            *(f"--external:{spec}" for spec in sorted(external_bare_specifiers())),
            *external_flags,
            f"--target={target}",
            "--resolve-extensions=.js,.mjs,.json",
            f"--outfile={out_path}",
            f"--metafile={metafile_path}",
            *sourcemap_flags,
            *alias_flags,
        ]
        try:
            self._run_esbuild(argv, timeout_s, entry_text, _t0)
            code = self._postprocess_esbuild_output(
                out_path,
                metafile_path,
                sourcemap_path,
                source_maps,
                entry_bytes,
                _t0,
            )
            return EsbuildResult(code, self._last_metafile, self._last_sourcemap)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _esbuild_stub_aliases(
        self,
        alias_flags: list[str],
        secondary_parent_stubs: dict[str, str] | None,
        tmp_dir: str,
        odoo_root: Path,
    ) -> list[str]:
        if not secondary_parent_stubs:
            return alias_flags
        stub_flags = self._write_stub_mirror(
            Path(tmp_dir) / "stubs", secondary_parent_stubs, alias_flags, odoo_root
        )
        if not stub_flags:
            return alias_flags
        stubbed = {
            flag.removeprefix("--alias:").partition("=")[0] for flag in stub_flags
        }
        return [
            flag
            for flag in alias_flags
            if flag.removeprefix("--alias:").partition("=")[0] not in stubbed
        ] + stub_flags

    def _esbuild_resolve_opts(
        self,
        timeout_s: int | None,
        target: str | None,
        source_maps: str | None,
    ) -> tuple[int, str, str]:
        if timeout_s is None:
            timeout_s = self._ESBUILD_TIMEOUT_S
        if target is None:
            target = self._ESBUILD_TARGET
        elif not all(
            self._ESBUILD_TARGET_TOKEN_RE.fullmatch(token.strip())
            for token in target.split(",")
        ):
            log_event(
                _esbuild_log,
                logging.WARNING,
                "target_invalid",
                bundle=self.name,
                target=target,
                fallback=self._ESBUILD_TARGET,
            )
            target = self._ESBUILD_TARGET
        if source_maps is None:
            source_maps = self._ESBUILD_SOURCE_MAPS
        if source_maps not in self._ESBUILD_SOURCE_MAP_MODES:
            log_event(
                _esbuild_log,
                logging.WARNING,
                "source_maps_unknown_mode",
                bundle=self.name,
                mode=source_maps,
                valid=sorted(m for m in self._ESBUILD_SOURCE_MAP_MODES if m),
            )
            source_maps = ""
        return timeout_s, target, source_maps

    def _esbuild_entry_lines(self, odoo_root: Path) -> list[str]:
        if self._standalone:
            entry_lines = []
            for asset in self.native_modules:
                if asset._filename:
                    path = os.path.relpath(asset._filename, odoo_root)
                else:
                    path = f"addons{asset.url}"
                entry_lines.append(f"import {json.dumps('./' + path)};")
            return entry_lines
        entry_lines = []
        register_entries = []
        registered_specs: set[str] = {"@odoo/owl"}
        entry_lines.append('import * as __owl from "@odoo/owl";')
        register_entries.append('  "@odoo/owl": __owl')
        _skip_legacy_test_imports = self._skip_legacy_test_imports
        for i, asset in enumerate(self.native_modules):
            spec = asset.module_path
            if _skip_legacy_test_imports and "/static/tests/" in (asset.url or ""):
                continue
            if asset._filename:
                path = os.path.relpath(asset._filename, odoo_root)
            else:
                path = f"addons{asset.url}"
            entry_lines.append(f"import * as __m{i} from {json.dumps('./' + path)};")
            register_entries.append(f"  {json.dumps(spec)}: __m{i}")
            registered_specs.add(spec)

        entry_lines.append("odoo.loader.registerNativeModules({")
        entry_lines.append(",\n".join(register_entries))
        entry_lines.append("});")

        alias_lines = []
        for ext_name, int_name in EXTERNAL_LIB_ALIASES.items():
            if int_name in registered_specs:
                alias_lines.append(
                    f"odoo.loader.modules.set({json.dumps(ext_name)},"
                    f"odoo.loader.modules.get({json.dumps(int_name)}));"
                )
        if alias_lines:
            entry_lines.extend(alias_lines)
        return entry_lines

    def _esbuild_flags(
        self,
        odoo_root: Path,
        dynamic_child_specs: frozenset[str] | None,
    ) -> tuple[list[str], list[str]]:
        alias_flags, test_external_flags = self._addon_flags_provider(odoo_root)
        bundle_test_addons: set[str] = set()
        for asset in self.native_modules:
            url = (asset.url or "").lstrip("/")
            parts = url.split("/")
            if len(parts) >= 3 and parts[1] == "static" and parts[2] == "tests":
                bundle_test_addons.add(parts[0])
        if bundle_test_addons:
            test_external_flags = [
                flag
                for flag in test_external_flags
                if not any(
                    f"--external:@{name}/../tests/" in flag
                    or f"/{name}/static/tests/" in flag
                    for name in bundle_test_addons
                )
            ]
        dynamic_external_flags: list[str] = []
        if dynamic_child_specs:
            dynamic_external_flags.extend(
                f"--external:{spec}" for spec in sorted(dynamic_child_specs)
            )

        for js_asset in self.javascripts + self.native_modules:
            header = js_asset.parsed_header
            if header and header["alias"] and header["alias"].startswith("@odoo/"):
                if js_asset._filename:
                    alias_path = os.path.relpath(js_asset._filename, odoo_root)
                else:
                    alias_path = f"addons{js_asset.url}"
                alias_flags.append(f"--alias:{header['alias']}=./{alias_path}")
        return alias_flags, test_external_flags + dynamic_external_flags

    @classmethod
    def _write_stub_mirror(
        cls,
        stub_root: Path,
        stubs: dict[str, str],
        alias_flags: list[str],
        odoo_root: Path,
    ) -> list[str]:
        addon_roots = {}
        for flag in alias_flags:
            spec, _, target = flag.removeprefix("--alias:").partition("=")
            if spec.startswith("@") and "/" not in spec:
                addon_roots[spec] = odoo_root / target.removeprefix("./")

        occupied: dict[str, set[str]] = {}
        must_be_real: set[str] = set()
        for spec in stubs:
            parent_rel, _, name = spec.lstrip("@").rpartition("/")
            occupied.setdefault(parent_rel, set()).add(f"{name}.js")
            while parent_rel:
                must_be_real.add(parent_rel)
                parent_rel = parent_rel.rpartition("/")[0]

        flags = []
        for spec in sorted(stubs):
            rel = spec.lstrip("@")
            stub_path = stub_root / rel
            stub_path.parent.mkdir(parents=True, exist_ok=True)
            real_dir = cls._stub_sibling_dir(spec, addon_roots)
            if real_dir is not None and not stub_path.exists():
                if rel in must_be_real:
                    cls._mirror_dir(stub_path, real_dir, rel, occupied, must_be_real)
                else:
                    stub_path.symlink_to(real_dir, target_is_directory=True)
            shim_path = stub_root / f"{rel}.js"
            cls._ensure_inside_mirror(shim_path, stub_root)
            shim_path.write_text(stubs[spec], encoding="utf-8")
            flags.append(f"--alias:{spec}={stub_path}")
        return flags

    @classmethod
    def _mirror_dir(
        cls,
        mirror: Path,
        real_dir: Path,
        rel: str,
        occupied: dict[str, set[str]],
        must_be_real: set[str],
    ) -> None:
        mirror.mkdir(parents=True, exist_ok=True)
        taken = occupied.get(rel, frozenset())
        for entry in real_dir.iterdir():
            if entry.name in taken:
                continue
            entry_rel = f"{rel}/{entry.name}"
            if entry_rel in must_be_real and entry.is_dir():
                cls._mirror_dir(
                    mirror / entry.name, entry, entry_rel, occupied, must_be_real
                )
            else:
                (mirror / entry.name).symlink_to(entry)

    @staticmethod
    def _ensure_inside_mirror(path: Path, stub_root: Path) -> None:
        resolved = path.parent.resolve()
        if not resolved.is_relative_to(stub_root.resolve()):
            raise RuntimeError(
                f"refusing to write the ESM shim {path.name!r} outside the stub "
                f"mirror: {resolved} is not under {stub_root}"
            )

    @staticmethod
    def _stub_sibling_dir(spec: str, addon_roots: dict[str, Path]) -> Path | None:
        addon, _, rest = spec.partition("/")
        root = addon_roots.get(addon)
        if root is None:
            return None
        candidate = root.joinpath(*rest.split("/"))
        return candidate if candidate.is_dir() else None

    @staticmethod
    def _purge_stale_fail_dumps(name: str) -> None:
        pattern = "esbuild_fail_" + glob.escape(name) + "_*.js"
        with contextlib.suppress(OSError):
            for stale in Path(tempfile.gettempdir()).glob(pattern):
                with contextlib.suppress(OSError):
                    stale.unlink()

    def _run_esbuild(
        self,
        argv: list[str],
        timeout_s: int,
        entry_text: str,
        _t0: float,
    ) -> None:
        try:
            result = subprocess.run(
                argv,
                input=entry_text,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout_s,
                cwd=str(Path(odoo.__path__[0]).parent),
                check=False,
            )
            if result.returncode != 0:
                self._purge_stale_fail_dumps(self.name)
                try:
                    with tempfile.NamedTemporaryFile(
                        mode="w",
                        prefix=f"esbuild_fail_{self.name}_",
                        suffix=".js",
                        delete=False,
                        encoding="utf-8",
                    ) as debug_file:
                        debug_file.write(entry_text)
                        debug_path = debug_file.name
                except OSError:
                    debug_path = "(write failed)"
                log_event(
                    _esbuild_log,
                    logging.WARNING,
                    "failed",
                    bundle=self.name,
                    exit=result.returncode,
                    entry=debug_path,
                    elapsed=f"{time.monotonic() - _t0:.3f}",
                )
                _esbuild_log.warning(
                    "esbuild stderr for %s:\n%s",
                    self.name,
                    result.stderr,
                )
                raise RuntimeError(
                    f"esbuild failed (exit {result.returncode}): {result.stderr[:500]}"
                )
        except subprocess.TimeoutExpired:
            log_event(
                _esbuild_log,
                logging.ERROR,
                "timeout",
                bundle=self.name,
                timeout_s=timeout_s,
            )
            raise RuntimeError(f"esbuild timed out after {timeout_s}s") from None

    def _postprocess_esbuild_output(
        self,
        out_path: str,
        metafile_path: str,
        sourcemap_path: str,
        source_maps: str,
        entry_bytes: int,
        _t0: float,
    ) -> str:
        try:
            bundle_text = Path(out_path).read_text(encoding="utf-8")
        except OSError as out_err:
            raise RuntimeError(
                f"esbuild exited 0 but output file missing: {out_err}"
            ) from out_err

        try:
            self._last_metafile = Path(metafile_path).read_text(encoding="utf-8")
        except OSError as mf_err:
            log_event(
                _esbuild_log,
                logging.DEBUG,
                "metafile_unavailable",
                bundle=self.name,
                err=type(mf_err).__name__,
            )
            self._last_metafile = None

        self._last_sourcemap = None
        if source_maps in ("linked", "external"):
            try:
                self._last_sourcemap = Path(sourcemap_path).read_text(
                    encoding="utf-8",
                )
            except OSError as sm_err:
                log_event(
                    _esbuild_log,
                    logging.DEBUG,
                    "sourcemap_unavailable",
                    bundle=self.name,
                    err=type(sm_err).__name__,
                )

        if source_maps == "linked":
            expected_name = f"{self.name}.esm.js.map"
            bundle_text = re.sub(
                r"//# sourceMappingURL=\S+(?=\s*\Z)",
                f"//# sourceMappingURL={expected_name}",
                bundle_text,
            )

        elapsed = time.monotonic() - _t0
        output_bytes = len(bundle_text)
        log_event(
            _esbuild_log,
            logging.INFO,
            "bundled",
            bundle=self.name,
            modules=len(self.native_modules),
            input_bytes=entry_bytes,
            output_bytes=output_bytes,
            ratio=f"{output_bytes / entry_bytes:.2f}" if entry_bytes else "n/a",
            elapsed=f"{elapsed:.3f}",
        )
        return bundle_text
