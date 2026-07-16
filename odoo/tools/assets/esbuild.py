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

import functools
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

# Bare-specifier prefix marked external at the pattern level: ``compile``
# passes ``--external:{EXTERNAL_SPECIFIER_PREFIX}*`` so esbuild leaves these
# imports verbatim for the browser's import map to resolve.  Public because
# ``AssetsBundle._validate_external_libs`` derives pattern coverage from the
# same constant the flag is built from (one source — the two used to be
# parallel hand-maintained lists).
EXTERNAL_SPECIFIER_PREFIX = "@odoo/"

# Third-party libraries shipped as real ES modules under ``static/lib`` and
# resolved through the browser import map (``ODOO_EXTERNAL_LIBS``) rather than
# inlined by esbuild.  Unlike the ``@odoo/*`` prefix these are bare npm-style
# specifiers with no shared prefix, so ``compile`` emits one explicit
# ``--external:<spec>`` per entry.  Marking them external (instead of aliasing
# them through ``_LIB_CANDIDATES``) means each lib is fetched ONCE via the
# import map and shared across every bundle — a single ``luxon`` instance
# whose ``Settings`` the whole app (and the Chart date adapter) agree on,
# instead of a 260 KB copy inlined into every esbuild bundle.  Eager libs
# (loaded at module-eval) and lazy libs (pulled in by a dynamic ``import()``
# in a loader wrapper) are handled identically — the import map resolves both;
# the laziness comes from the call site, not the externalization.
#
# Kept in sync with ``ODOO_EXTERNAL_LIBS`` (the import-map URLs) by
# ``AssetsBundle._validate_external_libs`` at startup: every entry here must
# have an import-map URL, and every non-``@odoo/*`` import-map key that isn't
# inlined via ``_LIB_CANDIDATES`` must appear here.
EXTERNAL_BARE_SPECIFIERS = frozenset(
    {
        "luxon",
        # DOMPurify (upstream ESM build).  Shared as one instance so the
        # html_editor's per-iframe ``DOMPurify(window)`` factories and the
        # one-off ``DOMPurify.sanitize`` callers agree on the same library
        # copy — replacing the old eager UMD ``<script>`` +
        # ``window.DOMPurify`` global.
        "dompurify",
        # signature_pad (upstream ESM build), lazily pulled in by
        # ``@web/components/signature/name_and_signature`` via dynamic
        # ``import()`` — replacing the old ``web.assets_signature_pad_lib``
        # classic bundle + ``window.SignaturePad`` global.
        "signature_pad",
        # ZXing barcode library (single-file ESM bundle built from upstream
        # ``@zxing/library`` esm/ sources — see the banner in the vendored
        # file).  Lazily pulled in by the barcode video scanner and the
        # QR-writer call sites via dynamic ``import()``; statically imported
        # by ``l10n_sa_pos`` (sync receipt rendering) — replacing the old
        # eager UMD bundle member + ``window.ZXing`` global.
        "zxing-library",
        # pdf.js main library (the vendored ``build/pdf.js`` IS the upstream
        # ESM build — it always was; only the consumption was global-based).
        # Lazily pulled in by ``@web/core/utils/pdfjs.loadPDFJS`` and by the
        # website_slides embed viewer via dynamic ``import()``.  Evaluating
        # the module also assigns ``globalThis.pdfjsLib`` (webpack build
        # artifact), which the classic ``PDFSlidesViewer.js`` helper relies
        # on.  The worker stays a plain URL (``build/pdf.worker.js``) handed
        # to ``GlobalWorkerOptions.workerSrc`` — pdf.js spawns it itself as
        # a module worker.
        "pdfjs-dist",
        "chart.js",
        # Stateless Chart.js helper utilities, shared by the geo/treemap
        # chart plugins (kept external so there is one copy, not one per
        # plugin bundle).
        "chart.js/helpers",
        "chartjs-adapter-luxon",
        # Spreadsheet's extra Chart.js plugins (geo maps, treemaps) and
        # survey's data-labels plugin.  They register onto the shared external
        # Chart and are pulled in by the spreadsheet / survey chart installers.
        "chartjs-chart-geo",
        "chartjs-chart-treemap",
        "chartjs-plugin-datalabels",
        "@fullcalendar/core",
        "@fullcalendar/core/locales-all",
    }
)


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
            timeout=timeout_s,
            check=False,  # returncode handled below; failure is non-fatal
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
        # Full stderr on its own line so field parsers don't have to
        # handle embedded newlines (same convention as _run_esbuild).
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
        # Normalize to lists: ``_esbuild_flags`` concatenates the two, and
        # the declared ``tuple`` default would TypeError on ``tuple + list``
        # (latent until callers stopped passing both explicitly).
        self.native_modules = list(native_modules)
        self.javascripts = list(javascripts)
        self._import_map_included = import_map_included
        self._skip_legacy_test_imports = skip_legacy_test_imports
        # Standalone bundles (esm.standalone_bundles) target non-page
        # runtimes (web workers): the entry imports modules only for their
        # side effects — no ``@odoo/owl`` external, no ``odoo.loader``
        # registration trailer, both of which would crash outside a page.
        self._standalone = standalone
        self._addon_flags_provider = (
            addon_flags_provider or self._get_esbuild_addon_flags
        )
        self._last_metafile: str | None = None
        self._last_sourcemap: str | None = None

    # Cache for the per-process esbuild addon-path scan.  The scan walks
    # every ``addons_path`` to build --alias and --external flags and
    # locate vendored @odoo/* library files.  The result depends on the
    # filesystem layout under ``odoo.addons.__path__``, so we compute
    # once and re-use across every bundle build.
    #
    # Auto-invalidated when ``__path__`` changes (the cache key is the
    # path tuple).  For new addon directories appearing inside an
    # existing ``addons_path`` entry the path tuple is unchanged, so
    # ``invalidate_addon_scan_cache()`` must be called explicitly — it
    # is invoked from ``ir.module.module.update_list()``, which is the
    # canonical "rescan addons from disk" entry point.
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

    # Canonical source of vendored @odoo/* library paths.  Promoted from
    # a local in _get_esbuild_addon_flags so that ``_validate_external_libs``
    # (called from ir_qweb after its _ODOO_EXTERNAL_LIBS map is defined)
    # can cross-check the import-map entries against the alias list.
    # Each value is a path-parts tuple joined under ``addon_dir`` at scan
    # time via ``Path.joinpath(*parts)``.
    _LIB_CANDIDATES: dict[str, tuple[str, ...]] = {
        "@odoo/hoot-dom": ("web", "static", "lib", "hoot-dom", "hoot-dom.js"),
        # Deep-import aliases for the hoot test runner's internals.  Hoot
        # uses ``isNode``, low-level event helpers, etc. that are not
        # re-exported from the public ``@odoo/hoot-dom`` surface.  The
        # legacy convention ``@web/../lib/hoot-dom/helpers/dom`` is
        # rejected by chrome's import-map resolver in ``?debug=assets``
        # mode (chrome blocks ``..`` backtracking — see commit message
        # of ``[FIX] base: bridge-shim persist falls back to data: URI on
        # read-only cursor`` for the full chain), so the 13 hoot internal
        # files import through these flat top-level aliases instead.
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
        "@popperjs/core": (
            "web",
            "static",
            "lib",
            "popper",
            "popper.esm.js",
        ),
        "@odoo/o-spreadsheet": (
            "spreadsheet",
            "static",
            "src",
            "o_spreadsheet",
            "o_spreadsheet.js",
        ),
        # NOTE: ``luxon`` used to live here as an esbuild alias onto a tiny
        # ``luxon.esm.js`` shim that re-exported ``window.luxon`` (set by the
        # vendored UMD IIFE).  It is now a real ES module
        # (``lib/luxon/luxon.js``) resolved through the import map as an
        # EXTERNAL bare specifier — see :data:`EXTERNAL_BARE_SPECIFIERS`.  The
        # same move retired the eager ``luxon.js`` ``<script>`` from every
        # manifest bundle and the ``globalThis.luxon`` global it installed.
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
        # Per-addon loop: build alias for the addon's static/src and
        # external flags for its static/tests in ONE pass.  First
        # directory wins when an addon name appears in several
        # addons_path entries: Python resolves namespace packages
        # first-path-wins, while esbuild resolves duplicate ``--alias``
        # flags last-wins (verified empirically, 2026-06-09) — emitting
        # both flags would make the JS resolve from the OPPOSITE tree
        # to the Python module.
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

        # Vendored @odoo/* lib aliases.  Located dynamically because the
        # index order depends on addons_path configuration.  The
        # canonical mapping now lives on the class so that
        # ``_validate_external_libs`` can check drift against
        # ir_qweb._ODOO_EXTERNAL_LIBS.
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
        # Return fresh copies so per-bundle mutations by the caller can
        # never poison the process-cached lists.
        return list(alias_flags), list(test_external_flags)

    # Hardcoded defaults for the esbuild subprocess; operators can
    # override via ``web.esbuild.{timeout_s,target,source_maps}``.
    # Kept as class constants so callers that don't have env access can
    # still construct a valid invocation.
    _ESBUILD_TIMEOUT_S: int = 30
    # ``es2023`` lets esbuild drop the ``Promise.withResolvers`` downlevel
    # polyfill (already used by ``core/network/rpc.js``).  All es2023 features
    # have >18mo baseline across Chrome 110+/Safari 16+/FF 115+.
    _ESBUILD_TARGET: str = "es2023"
    # Syntactic gate for ``--target`` values (comma-separated tokens such as
    # ``es2023``, ``esnext``, ``chrome58,node12.20``).  Not a semantic check —
    # esbuild's accepted engine list evolves — but it catches the garbage a
    # typo'd ``web.esbuild.target`` config param would otherwise pass straight
    # into the subprocess, failing every build until the breaker opens.
    _ESBUILD_TARGET_TOKEN_RE = re.compile(r"[a-z]+\d*(?:\.\d+)*")
    # Source-map mode.  Values match esbuild's ``--sourcemap=<mode>``:
    #
    #   ``""``        off — no ``.js.map`` sidecar emitted.
    #   ``"linked"``  (default) sidecar ``.js.map`` attachment + a
    #                 ``//# sourceMappingURL=<basename>.map`` comment
    #                 in the bundle so devtools fetches the map only
    #                 when opened.  Zero runtime cost when closed,
    #                 full debug surface when open.
    #   ``"external"`` sidecar attachment but NO comment in the bundle.
    #                 Useful if you distribute maps out-of-band
    #                 (e.g. to a crash reporter) and don't want devtools
    #                 picking them up automatically.
    #   ``"inline"``  base64-encoded data URL appended to the bundle.
    #                 No extra HTTP round-trip but ~2x bundle size.
    # Off by default. ``test_off_by_default`` codifies this contract;
    # the docstring on ``esbuild_native_bundle`` documents ``""`` as the
    # default. Producing a 3.6 MB ``.esm.js.map`` sibling on every bundle
    # rebuild (driven by the assets cursor) is wasteful when nobody is
    # debugging in the browser, so callers that want source maps opt in
    # explicitly via ``source_maps="linked"`` or via a fork-local
    # override of this class attribute.
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

        # Bundles whose specifiers are included in a parent bundle's
        # import map skip esbuild — their test files are loaded lazily
        # via import() in Hoot factories, not bundled. Membership is
        # decided by AssetsBundle and passed in (taxonomy stays there).
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
        # Entry size helps diagnose pathological imports (e.g. a glob that
        # pulls thousands of specs).
        entry_bytes = len(entry_text.encode("utf-8"))

        alias_flags, external_flags = self._esbuild_flags(
            odoo_root, dynamic_child_specs
        )

        # The entry is piped on stdin — esbuild resolves its relative
        # imports against the cwd (``odoo_root``), so nothing is written
        # into the code tree: works on read-only deployments and leaves
        # no debris on hard kills.  Metafile requires ``--outfile=``
        # (esbuild refuses to emit it when the bundle goes to stdout),
        # so the outputs go to a private temp dir removed as a unit.
        tmp_dir = tempfile.mkdtemp(prefix=f"odoo-esbuild-{self.name}-")
        out_path = str(Path(tmp_dir) / "bundle.out.js")
        metafile_path = str(Path(tmp_dir) / "bundle.meta.json")

        # Secondary-bundle singleton stubs: write each shim to a temp file and
        # add a MODULE-EXACT ``--alias`` so esbuild inlines the shim (which
        # reads ``odoo.loader.modules``) instead of a second copy of the shared
        # module. Exact ``--alias:@web/core/browser/browser=…`` outranks the
        # ``@web`` package alias, so ONLY these specifiers are redirected; the
        # bundle's other ``@web/*`` imports still resolve+inline normally. The
        # stub dir lives under ``tmp_dir`` and is removed with it.
        alias_flags = list(alias_flags)
        if secondary_parent_stubs:
            stub_dir = Path(tmp_dir) / "stubs"
            stub_dir.mkdir()
            for i, (spec, shim_js) in enumerate(sorted(secondary_parent_stubs.items())):
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
        # Source-map output flag.  ``--sourcemap=linked`` writes the map
        # to ``<outfile>.map`` and appends a
        # ``//# sourceMappingURL=<basename>.map`` comment to the bundle,
        # so the browser knows where to look when devtools opens;
        # ``--sourcemap=external`` writes the same sidecar without the
        # comment.  ``--sourcemap=inline`` embeds the map as a base64
        # data URL.  An empty ``source_maps`` skips the flag entirely.
        sourcemap_flags = [f"--sourcemap={source_maps}"] if source_maps else []
        sourcemap_path = f"{out_path}.map"
        argv = [
            esbuild,
            "--bundle",
            "--format=esm",
            "--minify",
            "--keep-names",
            f"--external:{EXTERNAL_SPECIFIER_PREFIX}*",
            # Vendored libraries under /web/static/lib are runtime assets
            # served by the static handler and pulled in via lazy
            # ``import("/web/static/lib/.../x.esm.js")`` calls (e.g. Chart,
            # FullCalendar). esbuild runs with cwd=odoo_root, so a leading-/
            # specifier resolves as a filesystem-absolute path that never
            # exists and the build fails. Mark them external so esbuild emits
            # the import verbatim for the browser to resolve at request time.
            "--external:/web/static/lib/*",
            # Real-ESM third-party libs resolved through the import map and
            # shared across bundles (luxon, Chart.js + its luxon date adapter,
            # FullCalendar + locales).  Emitted verbatim so the browser
            # resolves them once via ``ODOO_EXTERNAL_LIBS`` instead of esbuild
            # inlining a copy into every bundle.  See EXTERNAL_BARE_SPECIFIERS.
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
            # _postprocess set the _last_* captures just above.
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
        # Specifiers actually handed to ``registerNativeModules`` — used
        # below to decide which @odoo/* external aliases to wire up, via an
        # O(1) set lookup instead of substring-scanning the rendered
        # ``register_entries`` strings (which only worked because json.dumps
        # happens to include the closing quote).
        registered_specs: set[str] = {"@odoo/owl"}
        # Register @odoo/owl explicitly — externalized by esbuild
        # (resolved via import map) but must be in registerNativeModules
        # so bridge modules and other ``odoo.loader.modules.get()``
        # consumers (cross-doc iframes, hoot fixtures) can find the owl
        # namespace under its specifier.
        entry_lines.append('import * as __owl from "@odoo/owl";')
        register_entries.append('  "@odoo/owl": __owl')
        # ``web.assets_unit_tests_setup`` (and any future bundle in
        # ``esm.import_map_includes``) ships a runtime test-loader that
        # imports children lazily via ``import()`` against the parent's
        # import map; under that flow the legacy ``@web/../tests/...``
        # specifiers resolve via the import map, not via esbuild.  For
        # other bundles (e.g. ``web.assets_tests``, which the browser
        # loads eagerly so tour JS executes its top-level
        # ``registry.add`` calls) test files MUST go through esbuild —
        # otherwise the bundle ships without them and tours never
        # register, even though the import map advertises them.
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

        # Register @odoo/* external library aliases so that bridge
        # modules (attachment shims under ``/web/assets/esm/bridges/``,
        # or runtime ``data:`` bridges — both resolve specifiers via
        # ``odoo.loader.modules.get()``) can find these modules.  The
        # esbuild bundle registers modules under their internal
        # specifiers (e.g. @web/../lib/hoot/hoot) but the import map
        # carries bridges for the @odoo/* names.
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
        # Drop external patterns that would exclude this bundle's OWN
        # test files.  ``test_external_flags`` is shaped for production
        # bundles where stray ``static/tests/*`` imports must NOT pull
        # test code into the runtime bundle.  But ``web.assets_tests``
        # (and any other bundle whose contract IS to ship test files)
        # must include those very files; without this filter esbuild
        # marks them ``--external``, the entry's ``import * as`` becomes
        # a runtime fetch against a URL the server doesn't expose, and
        # all top-level side effects (``registry.add(...)`` tour
        # registrations) silently never execute.
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
        # Per-call externals for specs owned by a dynamic child bundle.
        # Kept separate from ``test_external_flags`` because that list
        # is process-cached; a per-call addition here must NEVER mutate
        # the cached tuple or other bundles would inherit the externals.
        dynamic_external_flags: list[str] = []
        if dynamic_child_specs:
            dynamic_external_flags.extend(
                f"--external:{spec}" for spec in sorted(dynamic_child_specs)
            )

        # Resolve @odoo/* aliases declared in bundle JS files so esbuild
        # can inline them instead of externalizing.  --alias takes
        # precedence over --external, so @odoo/hoot-dom (aliased to a
        # real file) gets bundled while @odoo/owl stays external.
        for js_asset in self.javascripts + self.native_modules:
            header = js_asset.parsed_header
            if header and header["alias"] and header["alias"].startswith("@odoo/"):
                if js_asset._filename:
                    alias_path = os.path.relpath(js_asset._filename, odoo_root)
                else:
                    alias_path = f"addons{js_asset.url}"
                alias_flags.append(f"--alias:{header['alias']}=./{alias_path}")
        return alias_flags, test_external_flags + dynamic_external_flags

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
                timeout=timeout_s,
                cwd=str(Path(odoo.__path__[0]).parent),
                check=False,  # returncode is inspected explicitly below
            )
            if result.returncode != 0:
                # Preserve the entry for post-mortem inspection. Use a unique
                # temp file (0600, unpredictable name) rather than a deterministic
                # /tmp/esbuild_fail_<bundle>.js path: the latter is symlink-
                # followable by a local user, who could pre-create it pointing at
                # a file the Odoo user may write, turning a build failure into an
                # arbitrary-file overwrite (CWE-377/59).
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
                # Keep the full stderr on a separate log line so field
                # parsers don't have to handle embedded newlines.
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
        # Read the bundle from the output file — stdout is empty
        # when ``--outfile`` is used.  This must happen before the
        # ``finally`` block deletes the temp artifacts.
        try:
            bundle_text = Path(out_path).read_text(encoding="utf-8")
        except OSError as out_err:
            raise RuntimeError(
                f"esbuild exited 0 but output file missing: {out_err}"
            ) from out_err

        # Metafile is best-effort — losing it only costs us the
        # analysis side-channel, not the main bundle.
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

        # Source map (``linked`` + ``external`` modes) — esbuild
        # wrote the ``.map`` next to the output; consumer
        # (IrQweb._save_esm_attachment) reads
        # ``self._last_sourcemap`` and persists the sibling
        # attachment.  ``inline`` mode embeds the map in the bundle
        # itself, so nothing extra to capture.  Failure to read is
        # non-fatal — sourcemaps are a debugging aid, not a
        # correctness requirement.
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

        # Rewrite the ``//# sourceMappingURL=<name>.map`` directive.
        # esbuild emits the directive with the TEMP output filename
        # (``tmp<random>.js.out.js.map``) because that's what it
        # just wrote.  The final attachment lives at
        # ``/web/assets/esm/<hash>/<bundle>.esm.js.map`` — same
        # directory as the bundle, so a relative filename is
        # enough.  Without this rewrite devtools fetches the
        # literal tmp name and 404s.  Only applies to ``linked``
        # mode (``external`` doesn't emit the directive;
        # ``inline`` embeds the map via a data URL that doesn't
        # need rewriting).
        if source_maps == "linked":
            expected_name = f"{self.name}.esm.js.map"
            bundle_text = re.sub(
                r"//# sourceMappingURL=\S+",
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
            # Ratio of minified output to entry-import glue; useful
            # to spot bundles whose esbuild output grows unexpectedly
            # between releases.
            ratio=f"{output_bytes / entry_bytes:.2f}" if entry_bytes else "n/a",
            elapsed=f"{elapsed:.3f}",
        )
        return bundle_text
