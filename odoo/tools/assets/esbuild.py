"""esbuild subprocess layer for the assets pipeline (H2 split, Phase B).

``EsbuildCompiler`` owns everything that talks to the esbuild binary:
binary discovery, the per-process addon-path scan (``--alias`` /
``--external`` flags), entry-point generation, option resolution, the
subprocess invocation and output post-processing. It is env-free — the
bundle taxonomy decisions (which bundles are ESM, which skip esbuild)
stay in ``AssetsBundle``, which passes them in as booleans and exposes a
thin ``esbuild_native_bundle`` wrapper for backward compatibility.

Extracted verbatim from ``odoo.addons.base.models.assetsbundle``
(2026-06-10); the only intentional changes are the seam parameters and
the ``EsbuildResult`` return value documented on ``compile``.
"""

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

EXTERNAL_BARE_SPECIFIERS = frozenset(
    {
        "luxon",
        "dompurify",
        "signature_pad",
        "zxing-library",
        "pdfjs-dist",
        "chart.js",
        "chart.js/helpers",
        "chartjs-adapter-luxon",
        "chartjs-chart-geo",
        "chartjs-chart-treemap",
        "chartjs-plugin-datalabels",
        "@fullcalendar/core",
        "@fullcalendar/core/locales-all",
    }
)


def is_module_exact_specifier(spec: str) -> bool:
    """Can *spec* be wired as a MODULE-EXACT esbuild ``--alias``?

    Only a specifier naming a module INSIDE a package (``@web/core/registry``)
    can: esbuild resolves ``--alias:pkg=target`` as a PACKAGE alias, so a bare
    ``--alias:@spreadsheet=<stub>`` would also capture every ``@spreadsheet/…``
    subpath and redirect it into the one-module stub. Callers that build loader
    shims must route the bare specifiers this rejects to ``--external`` instead,
    which leaves the import untouched for the page's import map to resolve.
    """
    return "/" in spec


class EsbuildResult(NamedTuple):
    """Outcome of one esbuild compilation."""

    code: str
    metafile: str | None
    sourcemap: str | None


@functools.cache
def _find_esbuild() -> str | None:
    """Locate the esbuild binary once per process (PATH, then node_modules)."""
    odoo_root = Path(odoo.__path__[0]).parent
    return shutil.which("esbuild") or shutil.which(
        "esbuild",
        path=str(odoo_root / "node_modules" / ".bin"),
    )


_TEMPLATE_LITERAL_TOKENS = re.compile(r"\\.|`|\$\{|\}", re.DOTALL)


def has_nested_template_literal(source: str) -> bool:
    """Whether *source* nests a template literal inside a ``${…}`` substitution.

    This is the one JS construct rjsmin 1.2.5 mangles: it tracks the outer
    literal but re-enters whitespace-collapsing mode inside the substitution,
    so ```A${`B  ${1}  C`}D``` loses the inner literal's spaces. A plain
    template literal — interpolated or not, multi-line or not — survives
    rjsmin intact.

    Deliberately conservative rather than a JS parser: a backtick inside a
    string, a comment or a regex literal can desynchronise the depth stack, and
    every such desync errs toward returning ``True``. A false positive costs
    one esbuild subprocess; a false negative would ship corrupted JS.

    Validated against acorn over every ``.js`` under all five addons roots
    (2158 files hold both a backtick and a ``${`` — the condition this
    replaced; 35 MB). Comparing the parsed template-literal chunks of the
    source against those of ``rjsmin(source)``: 49 flagged here, 11 of which
    rjsmin genuinely alters (one, ``ol.js``, it renders unparseable),
    **0 missed**. So 97.7% of those files keep the in-process minifier instead
    of paying ~5 ms of subprocess each.

    Do NOT re-validate by diffing ``esbuild --minify`` of both sides: that
    reports differences which are not corruption at all — rjsmin drops
    ``/** @license`` blocks that esbuild keeps, and its whitespace removal
    changes esbuild's ``var`` statement-merging. Both produced false
    "corrupted" verdicts on ``prism.js`` and ``three.module.js``. Compare
    parsed template-literal chunks, which is the actual question.

    :param source: JS source text
    :return: whether rjsmin must be bypassed for this source
    """
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
    """Minify one classic (non-module) JS source through esbuild.

    Used by ``JavascriptAsset.minify`` for legacy concatenation members
    that rjsmin cannot safely handle (rjsmin 1.2.5 corrupts NESTED
    template literals). ``--loader=js`` with no format conversion keeps
    classic-script/IIFE semantics; ``--legal-comments=inline`` mirrors
    rjsmin's ``keep_bang_comments``.

    :param source: JS source text
    :param label: asset identifier, for logging only
    :param timeout_s: subprocess budget; a hung binary must not pin a worker
    :return: minified JS, or ``None`` when esbuild is unavailable, fails or
        times out — the caller ships the source unminified (never an error)
    :rtype: str | None
    """
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
    """Compile a bundle's native ES modules through the esbuild binary.

    Stateless apart from the per-call ``_last_metafile`` /
    ``_last_sourcemap`` captures folded into the ``EsbuildResult``; build
    one instance per compilation (``AssetsBundle._make_esbuild_compiler``).

    :param name: bundle name (logging + entry generation)
    :param native_modules: assets exposing ``module_path`` / ``_filename``
        / ``url`` / ``parsed_header`` (duck-typed ``JavascriptAsset``)
    :param javascripts: legacy assets scanned for ``@odoo/*`` header
        aliases
    :param import_map_included: bundle rides a parent's import map —
        skip esbuild entirely
    :param skip_legacy_test_imports: bundle is an ``esm.import_map_includes``
        parent — its ``static/tests`` files load lazily, not via esbuild
    :param addon_flags_provider: ``f(odoo_root) -> (alias, externals)``
        override; defaults to the class-level cached scan. Injection
        point for tests (and the seam ``AssetsBundle`` routes through so
        ``patch.object(AssetsBundle, "_get_esbuild_addon_flags", …)``
        keeps working).
    """

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
        """Capture the bundle state one compilation needs (see class doc)."""
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
        """Clear the per-process esbuild addon-flag scan cache.

        Call this when the filesystem layout under ``addons_path`` may
        have changed since process start (new addon directory appearing
        in an existing path entry).  The next call to
        ``_get_esbuild_addon_flags`` will re-scan and rebuild the alias
        and external flag lists.
        """
        cls._esbuild_addon_scan_cache = None

    @classmethod
    def resolves_specifier(cls, spec: str) -> bool:
        """Whether a production build resolves the bare specifier *spec*.

        True when the specifier is covered by the pattern-level ``@odoo/*``
        external flag, listed in :data:`EXTERNAL_BARE_SPECIFIERS` (left
        verbatim for the browser's import map), or has a per-lib alias in
        :attr:`_LIB_CANDIDATES` (inlined at build time).

        :param spec: bare import specifier (e.g. ``@odoo/owl``)
        :rtype: bool
        """
        return (
            spec.startswith(EXTERNAL_SPECIFIER_PREFIX)
            or spec in EXTERNAL_BARE_SPECIFIERS
            or spec in cls._LIB_CANDIDATES
        )

    _LIB_CANDIDATES: dict[str, tuple[str, ...]] = {
        "@odoo/hoot-dom": ("web", "static", "lib", "hoot-dom", "hoot-dom.js"),
        "@odoo/hoot-dom-helpers-dom": (
            "web",
            "static",
            "lib",
            "hoot-dom",
            "helpers",
            "dom.js",
        ),
        "@odoo/hoot-dom-helpers-events": (
            "web",
            "static",
            "lib",
            "hoot-dom",
            "helpers",
            "events.js",
        ),
        "@odoo/hoot-dom-helpers-time": (
            "web",
            "static",
            "lib",
            "hoot-dom",
            "helpers",
            "time.js",
        ),
        "@odoo/hoot-dom-utils": (
            "web",
            "static",
            "lib",
            "hoot-dom",
            "hoot_dom_utils.js",
        ),
        # Bootstrap is Popper's only importer and uses a single entry point,
        # which `popper_compat` reimplements over the in-house position
        # engine. Bundles alias the SOURCE module so esbuild inlines it and
        # follows its `@web/...` imports normally; the self-contained build
        # under static/lib exists only for import-map pages (see
        # ODOO_EXTERNAL_LIBS).
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
        """Return ``(alias_flags, test_external_flags)`` for esbuild.

        Derived from ``odoo.addons.__path__``; cached per process.  The
        cache is keyed by the tuple of addon paths so that a test that
        monkey-patches ``__path__`` still sees the fresh scan.
        """
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
        """Bundle native ESM modules into a single minified file using esbuild.

        Generates an entry point that re-exports all native modules as
        namespaces, runs esbuild to bundle + minify, and returns an
        :class:`EsbuildResult` carrying the output JS plus the metafile
        and sourcemap captures (``None`` when not produced). The bundled
        file is a self-contained ES module that calls
        ``registerNativeModules()`` to populate the module Map.

        :param timeout_s: subprocess timeout (seconds).  Defaults to
            ``_ESBUILD_TIMEOUT_S``; callers should pass the value from
            ``ir.qweb._get_esbuild_setting("timeout_s", ...)``.
        :param target: esbuild ``--target=<value>``.  Defaults to
            ``_ESBUILD_TARGET``.  Allows admins to tighten or relax the
            browser-support floor without a code change.
        :param source_maps: ``"linked"`` to emit a sidecar ``.js.map``
            plus a ``//# sourceMappingURL=`` comment in the bundle
            pointing at it; ``"external"`` to emit the same sidecar
            without that comment.  Both persist the map bytes to
            ``self._last_sourcemap`` for the caller to write as a
            sibling attachment.  ``"inline"`` embeds the source map as a
            base64 data URL at the end of the bundle (no sidecar but
            ~2x bundle size); ``""`` (default) skips source maps
            entirely.  Unknown modes silently fall back to ``""`` — the
            wrong mode would crash esbuild and we'd rather lose
            debugging info than lose the bundle.
        :param dynamic_child_specs: bare specifiers that ship with a
            dynamic child bundle (e.g. lazy ``@web/views/...`` modules
            loaded by an import-map bridge).  Each is added as a
            ``--external:<spec>`` flag so esbuild does not inline them
            into the parent bundle — at runtime they resolve against
            the page's import map to the child bundle's registration.
            ``None`` (default) skips this entirely.  Computed by
            ``ir.qweb`` from the manifest-declared ``esm.dynamic_children``.
        :param secondary_parent_stubs: ``{specifier: shim_js}`` for the
            specifiers this bundle shares with its parent app bundle (only set
            for ``secondary_import_map_includes`` bundles like
            ``web.assets_tests``).  Each shim is written to a temp file and
            wired as a MODULE-EXACT ``--alias`` (which beats the ``@addon``
            package alias, so esbuild inlines the tiny shim instead of a SECOND
            copy of ``@web/core/browser/browser`` / ``@web/core/registry`` / …).
            The shim reads ``odoo.loader.modules.get(spec)`` at eval time —
            the instance the parent app bundle registered — so the test bundle
            and the running app share one object (the identity
            ``patchWithCleanup(browser, …)`` and RPC's ``browser.fetch``
            depend on).  Relies on the parent bundle evaluating FIRST
            (app-before-tests document order).  ``None`` (default) skips it.

        Requires esbuild (``npm install`` in the Odoo root).
        """
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

        alias_flags = list(alias_flags)
        if secondary_parent_stubs:
            exact_stubs = {
                spec: shim_js
                for spec, shim_js in secondary_parent_stubs.items()
                if is_module_exact_specifier(spec)
            }
            bare_specs = sorted(secondary_parent_stubs.keys() - exact_stubs.keys())
            if bare_specs:
                log_event(
                    _esbuild_log,
                    logging.WARNING,
                    "bare_package_stub_skipped",
                    bundle=self.name,
                    specs=bare_specs,
                )
            if exact_stubs:
                stub_dir = Path(tmp_dir) / "stubs"
                stub_dir.mkdir()
                for i, (spec, shim_js) in enumerate(sorted(exact_stubs.items())):
                    stub_path = stub_dir / f"stub_{i}.js"
                    stub_path.write_text(shim_js, encoding="utf-8")
                    alias_flags.append(f"--alias:{spec}={stub_path}")

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
            *(f"--external:{spec}" for spec in sorted(EXTERNAL_BARE_SPECIFIERS)),
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

    def _esbuild_resolve_opts(
        self,
        timeout_s: int | None,
        target: str | None,
        source_maps: str | None,
    ) -> tuple[int, str, str]:
        """Resolve esbuild call options to concrete values.

        Applies the class-constant defaults and validates ``source_maps``
        (against ``_ESBUILD_SOURCE_MAP_MODES``) and ``target`` (against the
        syntactic ``_ESBUILD_TARGET_TOKEN_RE``); an invalid value falls back
        to the default rather than crashing esbuild on every build.
        """
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
        """Build the esbuild entry-point lines for this bundle's native modules.

        Emits the ``@odoo/owl`` import, one namespace import per native module,
        the ``registerNativeModules({...})`` call, and the
        ``odoo.loader.modules.set(...)`` aliases for the hoot family.  The
        caller joins these with newlines into the temp entry file.

        Standalone bundles skip all of that page-context glue: the entry
        imports each module purely for its side effects.
        """
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

        _ext_aliases = {
            "@odoo/hoot": "@web/../lib/hoot/hoot",
            "@odoo/hoot-dom": "@web/../lib/hoot-dom/hoot-dom",
            "@odoo/hoot-mock": "@web/../lib/hoot/hoot-mock",
        }
        alias_lines = []
        for ext_name, int_name in _ext_aliases.items():
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
        """Return ``(alias_flags, external_flags)`` for the esbuild invocation.

        ``alias_flags`` = the process-cached addon/library aliases plus any
        per-bundle ``@odoo/*`` aliases declared in this bundle's file headers.
        ``external_flags`` = the cached test externals (minus this bundle's OWN
        test files) followed by the per-call dynamic-child externals, in that
        order.
        """
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

    @staticmethod
    def _purge_stale_fail_dumps(name: str) -> None:
        """Remove this bundle's earlier ``esbuild_fail_<name>_*.js`` post-mortem
        dumps from the temp dir. Without this, a persistently-broken bundle
        writes a fresh ``delete=False`` dump on every retry and they accumulate
        unbounded on long-lived servers; keeping only the newest per bundle
        preserves the debugging value while bounding the footprint."""
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
        """Run esbuild with the entry piped on stdin; raise ``RuntimeError`` on failure.

        On a non-zero exit, writes the entry to ``/tmp`` for post-mortem and
        logs the failure (full stderr on its own line).  On timeout, logs and
        raises.  Output is left in the ``--outfile`` for the caller to read.
        """
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
        """Read esbuild output, capture metafile/sourcemap, return bundle JS.

        Sets ``self._last_metafile`` / ``self._last_sourcemap`` (best-effort),
        rewrites the ``//# sourceMappingURL=`` directive to the final
        attachment name in ``linked`` mode, and logs the ``bundled`` event.
        """
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
