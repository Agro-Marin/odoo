"""Pure ESM module-graph helpers for the assets pipeline (H2 split).

Everything here is env-free and subprocess-free: ``@odoo-module`` header
parsing, URL→specifier mapping, the module-syntax probe, the process-level
classification cache, ES-module export extraction (with recursive
``export * from`` expansion), bridge-shim source generation, and the
per-build export resolver. Extracted verbatim from
``odoo.addons.base.models.assetsbundle`` (2026-06-10), which re-imports
the public surface so existing consumers and tests keep their imports.
"""

import functools
import logging
import re
from pathlib import Path

from odoo.libs.asset_log import get_asset_logger, log_event
from odoo.libs.constants import DOTTED_ASSET_EXTENSIONS as EXTENSIONS
from odoo.tools.assets.esm_lexer import lex_module
from odoo.tools.json import scriptsafe as json
from odoo.tools.misc import file_open, file_path

_logger = logging.getLogger(__name__)
_bridge_log = get_asset_logger("bridge")


# ── Inlined from js_transpiler.py ──────────────────────

_URL_RE = re.compile(
    r"""
    /?(?P<module>\S+)    # /module name
    /([\S/]*/)?static/   # ... /static/
    (?P<type>src|tests|lib)  # src, test, or lib file
    (?P<url>/[\S/]*)     # URL (/...)
    """,
    re.VERBOSE,
)

_ODOO_MODULE_RE = re.compile(
    r"""
    \/(\/|\*)                          # /* or //
    .*                                 # any comment in between (optional)
    @odoo-module                       # '@odoo-module' statement
    (?P<ignore>\s+ignore)?             # module should not be transpiled (optional)
    (?P<native>\s+native)?             # native ES module (optional)
    (\s+alias=(?P<alias>[^\s*]+))?     # alias (optional)
    (\s+default=(?P<default>[\w$]+))?  # default export control (optional)
""",
    re.VERBOSE,
)


def _parse_odoo_module_header(content: str) -> re.Match[str] | None:
    """Parse the ``@odoo-module`` directive from the file header."""
    return _ODOO_MODULE_RE.search(content[:500])


def is_native_module(content: str) -> bool:
    """Detect if the file is a native ES module (``@odoo-module native``)."""
    result = _parse_odoo_module_header(content)
    return bool(result and result["native"])


def is_odoo_module(url: str, content: str) -> bool:
    """Detect if the file is an odoo module routed through the ESM pipeline."""
    result = _parse_odoo_module_header(content)
    if result and (result["ignore"] or result["native"]):
        return False
    # ``url`` may be empty for inline assets constructed outside ir_qweb.
    parts = url.split("/") if url else []
    if len(parts) > 1:
        addon = parts[1]
        if url.startswith((f"/{addon}/static/src", f"/{addon}/static/tests")):
            return True
    return bool(result)


def url_to_module_path(url: str) -> str:
    """Convert a file URL to an Odoo module specifier.

    Example: ``web/static/src/one/two/three.js`` → ``@web/one/two/three``
    """
    match = _URL_RE.match(url)
    if match:
        url = match["url"]
        if url.endswith(("/index.js", "/index")):
            url, _ = url.rsplit("/", 1)
        url = url.removesuffix(".js")
        match match["type"]:
            case "src":
                return f"@{match['module']}{url}"
            case "lib":
                return f"@{match['module']}/../lib{url}"
            case _:
                return f"@{match['module']}/../tests{url}"
    else:
        raise ValueError(
            f"The js file {url!r} must be in the folder "
            "'/static/src' or '/static/lib' or '/static/test'"
        )


# ── End inlined code ──────────────────────────────────────────────


# Top-level module-syntax probe for the legacy-bundle guard.  Deliberately
# NARROWER than the routing heuristic in ``is_odoo_module`` (which also
# claims plain non-module files under ``/static/src`` — harmless inside
# esbuild, fatal as a stub trigger): only statements that are a
# ``SyntaxError`` in a classic concatenated <script> should match.
# Dynamic ``import(...)`` is legal in classic scripts and must NOT match —
# hence the character class after ``import`` excludes ``(``.
_MODULE_SYNTAX_RE = re.compile(
    r"""^\s*(?:import\s*(?:["'{*]|\w+\s*(?:,|from\b))|export\b)""",
    re.MULTILINE,
)

# Block comments and template literals can contain line-anchored
# ``import``/``export`` text that is NOT module syntax — strip them before
# probing. Regex-level stripping is approximate (an unbalanced backtick can
# fuse regions), but it errs toward stripping MORE, which can only
# SUPPRESS the probe: a missed genuine module file still fails loudly in
# the browser, while a false stub silently breaks a working file — the
# costlier error. Corpus check 2026-06-10: 8,796 files, zero
# classifications change with stripping (this is future-proofing).
_JS_OPAQUE_RE = re.compile(r"/\*.*?\*/|`[^`]*`", re.DOTALL)


def has_module_syntax(content: str) -> bool:
    """Whether ``content`` contains top-level ES-module syntax.

    Strips block comments and template literals first so a commented-out
    ``export`` cannot trip the legacy-bundle stub.
    """
    return bool(_MODULE_SYNTAX_RE.search(_JS_OPAQUE_RE.sub("", content)))


@functools.lru_cache(maxsize=16384)
def _cached_module_classification(
    url: str, filename: str, last_modified: float | int
) -> bool:
    """Whether the JS file at ``filename`` belongs to the ESM pipeline.

    Process-level memo keyed by ``(url, filename, last_modified)`` so the
    repeated ``AssetsBundle`` constructions of one cold render (links cache,
    native-data cache, esbuild build, dynamic children) read each source once
    per (file, mtime) instead of once per construction.  An edited file gets
    a new mtime and therefore a fresh classification.
    """
    try:
        with file_open(filename, "rb", filter_ext=EXTENSIONS) as fp:
            # Classification only consumes the ``@odoo-module`` header —
            # ``_parse_odoo_module_header`` slices ``content[:500]`` — so a
            # 512-byte window replaces the whole-file read (a cold sweep of
            # web+mail alone read 6.3 MB to use 0.5 MB). ``errors="ignore"``
            # because a multibyte character split at the window edge must
            # not flip the verdict to "legacy": the header is pure ASCII
            # and unaffected by a mangled trailing character.
            content = fp.read(512).decode("utf-8", errors="ignore")
    except OSError, ValueError:
        # Unreadable sources are surfaced by the regular fetch path at
        # generation time (console.error stub); classify as legacy here.
        return False
    return is_native_module(content) or is_odoo_module(url, content)


# Regex set shared between ``_build_parent_self_bridge``
# and ``_build_native_to_legacy_bridge``: both need to enumerate the
# named exports of a JS source file so the bridge shim can
# re-export them via ``odoo.loader.modules.get(...)``.  Consolidating
# the regexes in one helper lets us add new patterns (e.g. destructured
# ``export const { Tooltip, Modal } = obj;``) without drift between the
# two bridge builders.
_ESM_EXPORT_PATTERNS: tuple[tuple[str, str], ...] = (
    # Direct declaration: ``export const X = …`` / ``let X`` / ``var X`` /
    # ``function X`` / ``class X`` / ``async function X``.
    (
        "decl",
        r"export\s+(?:const|let|var|function\*?|class|async\s+function\*?)\s+(\w+)",
    ),
    # Destructured declaration: ``export const { X, Y: Z } = obj;``.  The
    # standard regex above misses this because after ``const`` the next
    # token is ``{``, not an identifier.  @web/libs/bootstrap and a handful
    # of Bootstrap wrappers use this form to re-export library members in
    # bulk — the bridge shim MUST declare these as named exports, otherwise
    # ``import { Tooltip } from "@web/libs/bootstrap"`` raises SyntaxError
    # ("does not provide an export named ...") when resolved through a
    # bridge shim.
    #
    # NOTE on ordering: each pattern below runs as an INDEPENDENT
    # ``finditer`` pass over the full source — nothing is "consumed", and
    # tuple order does not affect the result (verified empirically,
    # 2026-06-09: extraction is invariant under full order reversal).
    # Overlaps are harmless: ``list`` also matches the brace body of
    # ``list_from`` occurrences, contributing the same names to the set
    # union; it cannot match this destructured form (``\s*`` between
    # ``export`` and ``{`` does not cross ``const``).
    ("destructured", r"export\s+(?:const|let|var)\s*\{([^}]+)\}\s*="),
    # Re-export list FROM another module: ``export { X, Y as Z } from "..."``.
    # Group 1 is the interior name list; group 2 is the source specifier
    # (currently unused — named re-exports are explicit, so group 1
    # already carries every name; only ``star_from`` needs resolution).
    ("list_from", r'export\s*\{([^}]+)\}\s*from\s*["\']([^"\']+)["\']'),
    # Plain re-export list: ``export { X, Y as Z }`` (no ``from``).
    ("list", r"export\s*\{([^}]+)\}"),
    # Wildcard re-export: ``export * from "..."`` — re-exports every named
    # export of the target module (default is NOT re-exported per ESM
    # spec).  Resolution requires reading the target's source, so
    # callers MUST pass a non-empty ``source_map`` if they want the
    # transitive names; otherwise the wildcard is silently skipped and
    # the caller will end up with an incomplete bridge
    # — see ``_build_parent_self_bridge`` for the wiring.  Group 1 is
    # the source specifier.
    ("star_from", r'export\s*\*\s*from\s*["\']([^"\']+)["\']'),
    # Namespace re-export: ``export * as ns from "..."`` — exposes all of
    # target's exports as a single named export.  Group 1 is the
    # namespace name; group 2 is the source specifier.  We treat this as
    # a single named export (the namespace name) — the bridge shim can
    # ``export const ns = _m?.ns;`` because the target module's namespace
    # object is what ``_m.ns`` would already be after esbuild bundling.
    ("ns_from", r'export\s*\*\s*as\s+(\w+)\s*from\s*["\']([^"\']+)["\']'),
)
# Compiled once at import time.  ``_extract_esm_exports`` runs per discovered
# specifier (hundreds on POS/test bundles), so re-compiling these patterns on
# every call was pure overhead.
_ESM_EXPORT_PATTERNS_COMPILED: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (kind, re.compile(pattern)) for kind, pattern in _ESM_EXPORT_PATTERNS
)
# ``export default …`` (with optional ``function`` / ``class`` /
# ``async function`` / identifier).  Kept separate since it returns a
# boolean rather than a name set.
_ESM_EXPORT_DEFAULT_RE_SRC = (
    r"export\s+default(?:\s+(?:async\s+)?(?:function\*?|class)(?:\s+\w+)?)?"
)
_ESM_EXPORT_DEFAULT_RE = re.compile(_ESM_EXPORT_DEFAULT_RE_SRC)

# Import-discovery regex for ``_discover_bridge_specifiers``: every import shape
# that pulls a specifier from an ``@addon`` module, unified into ONE alternation
# so each source file is scanned a single time (one ``finditer``).  Branches 1-3
# carry a binding and a ``from`` (named/star/default — the kind is read from
# whichever named group matched); per-branch whitespace is preserved exactly, a
# default import requires ``\s+`` around the binding while named/star allow
# ``\s*``.  Branch 4 is the bindingless side-effect form ``import "@addon/…";``
# (no ``from``), whose specifier lands in the ``side`` group: a low-overlap
# dynamic child that only side-effect-imports a parent specifier (t22867) would
# otherwise never bridge it and fail at runtime with "Failed to resolve module
# specifier".  Module-level so it compiles once instead of on every bundle build.
_IMPORT_ANY_RE = re.compile(
    r"import(?:"
    r"\s*(?P<named>\{[^}]+\})\s*"
    r"|\s*(?P<star>\*\s*as\s+\w+)\s+"
    # Mixed default+named / default+namespace: ``import D, { y } from …`` and
    # ``import D, * as ns from …``.  Only valid in that order (default first).
    # Discovery-only: this branch has no dedicated ``kind`` so the consumer
    # treats it as a named import, and the shim emits the default block
    # unconditionally plus every named export of the source, so BOTH the
    # default and the named bindings resolve.  Without it a dynamic child
    # that mixed-imports a parent specifier would never bridge it and fail at
    # runtime with "Failed to resolve module specifier" when the es-module-
    # lexer worker is unavailable (the worker already handles this shape).
    r"|\s+(?P<mixed>\w+\s*,\s*(?:\{[^}]+\}|\*\s*as\s+\w+))\s*"
    r"|\s+(?P<default>\w+)\s+"
    r")from\s*"
    r"""["'](?P<spec>@[^"']+)["']"""
    r"""|import\s*["'](?P<side>@[^"']+)["']"""
)


def _resolve_export_specifier(
    importing_specifier: str | None,
    target_path: str,
) -> str | None:
    """Resolve a re-export's ``from "X"`` specifier to a module key.

    Bare specifiers (``@web/core/l10n/utils/format_list``) pass through
    with any trailing ``.js`` stripped — the source map is keyed by the
    result.

    Relative specifiers (``./foo``, ``../bar/baz``) need joining against
    the importing file's specifier.  The result is a normalized bare
    specifier that the source map can look up.

    Returns ``None`` if the specifier can't be resolved (e.g. relative
    import without an importing context).  The caller silently drops
    unresolvable wildcards rather than crash the bundle build.
    """
    if not target_path.startswith("."):
        # Normalize bare specifier — strip trailing ``.js`` so the result
        # matches ``url_to_module_path``'s output (which strips it too,
        # see line 87).  Without this, ``export * from "@mail/foo.js"``
        # would resolve to ``@mail/foo.js`` and miss the source-map entry
        # keyed under ``@mail/foo``.
        return target_path.removesuffix(".js")
    if not importing_specifier:
        return None
    # importing_specifier looks like "@web/core/l10n/utils".
    # Drop the last segment (the file name) to get the directory.
    parent_parts = importing_specifier.rsplit("/", 1)
    if len(parent_parts) < 2:
        return None
    base = parent_parts[0]
    rel_parts = target_path.split("/")
    while rel_parts and rel_parts[0] in (".", ".."):
        if rel_parts[0] == "..":
            base = base.rsplit("/", 1)[0] if "/" in base else base
        rel_parts.pop(0)
    # Mirror ``url_to_module_path``'s ``.js`` stripping so re-exports like
    # ``export * from "./record.js"`` resolve to ``@mail/model/record``,
    # which is the source-map key, not ``@mail/model/record.js``.
    resolved = f"{base}/{'/'.join(rel_parts)}" if rel_parts else base
    return resolved.removesuffix(".js")


def _extract_esm_exports(
    src: str,
    source_map: dict[str, str] | None = None,
    importing_specifier: str | None = None,
    _visited: set[str] | None = None,
    _exports_cache: dict[str, set[str]] | None = None,
) -> tuple[set[str], bool]:
    """Return ``(named_exports, has_default)`` parsed from a JS source file.

    Primary path: the spec-compliant ``es-module-lexer`` worker
    (``odoo.tools.assets.esm_lexer.lex_module``) — a real lexer, immune
    to the comment/string false-positive class by construction.  When the
    worker is unavailable (no node, package missing, worker died) or the
    source doesn't lex, the historical regex extractor below takes over.
    Both paths share the same recursive ``export * from`` expansion,
    visited-set and memoization semantics.  Corpus cross-check
    2026-07-03: lexer and regex agree on every ``static/src`` file across
    all five addon roots.

    The regex path is robust against the common ES module export shapes
    used in the fork: declarations, re-export lists (with ``as``
    renames), destructured declarations, ``export {x} from "..."``,
    ``export * from "..."``, and ``export * as ns from "..."``.  Not a
    full parser — block comments and template literals are stripped first
    (``_JS_OPAQUE_RE``, same as ``has_module_syntax``) so an ``export``
    quoted in a docstring cannot inject a spurious name — the shim would
    emit ``export const Foo = _m?.Foo;`` (silently ``undefined``) or a
    false ``has_default``.

    :param src: Raw JS source as a string.
    :param source_map: Optional dict mapping module specifier → raw source.
        When provided, ``export * from "X"`` is recursively expanded by
        looking up ``X`` and unioning its named exports into the result.
        Without it, wildcard re-exports contribute nothing — the bridge
        ends up missing those names and consumers see "does not provide
        an export named …" errors at module-load time.
    :param importing_specifier: The bare specifier of the importing file
        (e.g. ``@web/core/l10n/utils``).  Required when the source has
        relative re-exports (``export * from "./foo"``); ignored otherwise.
    :param _visited: Internal — tracks specifiers already expanded so a
        circular ``export * from`` chain doesn't recurse forever.
    :param _exports_cache: Internal, opt-in — ``{specifier: names}`` memo
        shared across sibling calls so a re-export hub reached from several
        modules is expanded once.  Checked before ``_visited`` because a
        cached entry is the target's COMPLETE surface.  Only safe for the
        acyclic ``export *`` graphs the fork has; omit it (the default) for
        the general case.
    """
    visited = _visited if _visited is not None else set()
    names: set[str] = set()

    def expand_star(raw_target: str) -> None:
        """Union the transitive surface of ``export * from raw_target``.

        Shared by the lexer and regex paths.  Memoized expansion (opt-in
        via ``_exports_cache``): a barrel reached through several modules'
        chains is parsed once.  The cache is checked BEFORE ``visited``
        because a cached entry is the target's COMPLETE transitive
        surface — correct to reuse even where ``visited`` would otherwise
        skip it.  Safe for the acyclic ``export *`` graphs the fork has;
        callers that might introduce a circular ``export *`` simply pass
        no cache.
        """
        target_spec = _resolve_export_specifier(importing_specifier, raw_target)
        if _exports_cache is not None and target_spec in _exports_cache:
            names.update(_exports_cache[target_spec])
            return
        # ``source_map is None`` (not falsy!): a lazy source map is an
        # empty dict at first call but becomes non-empty as entries are
        # populated.  Bool-checking the dict would short-circuit the very
        # first recursion that would populate it.
        if not target_spec or source_map is None or target_spec in visited:
            return
        target_src = source_map.get(target_spec)
        if target_src is None:
            return
        visited.add(target_spec)
        child_names, _ = _extract_esm_exports(
            target_src,
            source_map=source_map,
            importing_specifier=target_spec,
            _visited=visited,
            _exports_cache=_exports_cache,
        )
        names.update(child_names)
        if _exports_cache is not None:
            _exports_cache[target_spec] = child_names

    lexed = lex_module(src)
    if lexed is not None:
        names.update(lexed["names"])
        for raw_target in lexed["starFrom"]:
            expand_star(raw_target)
        return names, lexed["hasDefault"]

    src = _JS_OPAQUE_RE.sub("", src)
    for kind, pattern in _ESM_EXPORT_PATTERNS_COMPILED:
        for match in pattern.finditer(src):
            if kind == "decl":
                names.add(match.group(1))
            elif kind in ("list", "destructured", "list_from"):
                # All three yield a comma-separated body between braces in
                # group(1).  Split and take the post-``as`` binding
                # (``X as Y`` → exported name is ``Y``).  ``list_from``'s
                # group(2) is the source — we don't currently expand it
                # (named imports are explicit so we already have all names).
                for raw in match.group(1).split(","):
                    token = raw.strip().split(" as ")[-1]
                    # Strip destructuring alias syntax (``X: Y`` → ``Y``).
                    if ":" in token:
                        token = token.rsplit(":", 1)[-1]
                    # Strip default-value syntax (``X = def`` → ``X``).
                    if "=" in token:
                        token = token.split("=", 1)[0]
                    token = token.strip()
                    if token and token != "default":
                        names.add(token)
            elif kind == "ns_from":
                # ``export * as ns from "X"`` exposes a single named
                # export ``ns``.  No need to recurse into X — the
                # namespace itself is the export name.
                names.add(match.group(1))
            elif kind == "star_from":
                # ``export * from "X"`` — must resolve X and recurse.
                expand_star(match.group(1))
    has_default = bool(_ESM_EXPORT_DEFAULT_RE.search(src))
    return names, has_default


class _BridgeExportResolver:
    """Resolve ``@addon`` specifiers to source and extract their export surface.

    Per-build helper for ``BridgeShimManager._build_native_to_legacy_bridge``: reads
    the source file of each discovered specifier (with a disk-read cache) and
    extracts its export surface, recursively following ``export * from``.  The
    object doubles as the ``source_map`` passed to ``_extract_esm_exports`` —
    its ``get`` disk-reads on a miss — collapsing the old two-level cache
    (``_src_cache`` plus a ``_LazySourceMap`` dict) into one.
    """

    __slots__ = (
        "_bundle_name",
        "_cache",
        "_exports_cache",
        "_ext_libs",
        "_lib_candidates",
        "_star_cache",
    )

    def __init__(
        self,
        ext_libs: dict[str, str],
        lib_candidates: dict[str, tuple[str, ...]],
        bundle_name: str,
    ) -> None:
        self._ext_libs = ext_libs
        self._lib_candidates = lib_candidates
        self._bundle_name = bundle_name
        # Per-build disk-read cache so a re-export hub like
        # ``@web/core/l10n/utils`` doesn't re-read its targets each time it
        # appears in another module's ``export * from`` chain.
        self._cache: dict[str, str | None] = {}
        # Per-build parsed-export cache, keyed by spec. The same hub is
        # reached through many ``export * from`` chains in one build, and
        # extracting its surface is ~7 full-source regex passes — do it once.
        self._exports_cache: dict[str, tuple[set[str], bool]] = {}
        # Shared cache for the recursive ``export * from`` walk itself
        # (name sets only — distinct from ``_exports_cache``, whose values
        # are ``(names, has_default)`` tuples): a barrel reached through
        # several specs' chains is expanded once per build, mirroring what
        # ``_build_parent_self_bridge`` already did for its own walk.
        self._star_cache: dict[str, set[str]] = {}

    def resolve_url(self, spec: str) -> str | None:
        """Map an ``@addon/path`` specifier to a static URL.

        Mirrors the bridge resolver in ``ir_qweb._specifier_to_static_url``.
        Returns ``None`` for specifiers that cannot be mapped (e.g. bare
        ``luxon``) — external libs are handled through ``ext_libs``.
        """
        if spec in self._ext_libs:
            return self._ext_libs[spec]
        # Vendored libs aliased by esbuild (e.g. ``@odoo/o-spreadsheet``)
        # — not served via an import-map URL, so not in ``ext_libs``,
        # but the bridge still needs to introspect exports.
        lib_parts = self._lib_candidates.get(spec)
        if lib_parts:
            return "/" + "/".join(lib_parts)
        if not spec.startswith("@"):
            return None
        s = spec[1:]
        slash = s.find("/")
        if slash <= 0:
            return None
        addon = s[:slash]
        path = s[slash + 1 :]
        if path.startswith("../lib/"):
            url = f"/{addon}/static/lib/{path[len('../lib/') :]}"
        elif path.startswith("../tests/"):
            url = f"/{addon}/static/tests/{path[len('../tests/') :]}"
        else:
            url = f"/{addon}/static/src/{path}"
        if not url.endswith(".js"):
            url += ".js"
        return url

    def read_source(self, spec: str) -> str | None:
        """Read an addon-resolved specifier's source (cached, including misses)."""
        if spec in self._cache:
            return self._cache[spec]
        url = self.resolve_url(spec)
        if not url:
            self._cache[spec] = None
            return None
        try:
            parts = url.strip("/").split("/", 1)
            if len(parts) != 2:
                self._cache[spec] = None
                return None
            rel = f"{parts[0]}/static/{parts[1].split('static/', 1)[-1]}"
            try:
                fpath = file_path(rel)
            except FileNotFoundError, ValueError:
                # Directory-as-package fallback: ``@foo/bar`` whose
                # ``bar.js`` does not exist but ``bar/index.js`` does
                # (mirrors the Node/esbuild bare-specifier resolution
                # that handles these imports at bundle time).
                if rel.endswith(".js"):
                    fpath = file_path(rel[:-3] + "/index.js")
                else:
                    raise
            with Path(fpath).open(encoding="utf-8") as f:
                src = f.read()
            self._cache[spec] = src
            return src
        except (FileNotFoundError, ValueError, OSError) as exc:
            log_event(
                _bridge_log,
                logging.WARNING,
                "source_exports_read_failed",
                bundle=self._bundle_name,
                spec=spec,
                err=type(exc).__name__,
            )
            self._cache[spec] = None
            return None

    def get(self, key: str, default: str | None = None) -> str | None:
        """``source_map`` protocol: cached/disk-read source, or ``default``.

        Lets the resolver be passed as the ``source_map`` to
        ``_extract_esm_exports`` for the recursive ``export * from`` walk.
        """
        src = self.read_source(key)
        return src if src is not None else default

    def source_exports(self, spec: str) -> tuple[set[str], bool]:
        """Return ``(named_exports, has_default)`` by reading the source.

        Recursively follows ``export * from "..."`` re-exports so a barrel
        file like ``@web/core/l10n/utils`` exposes every name from its
        sub-modules through the bridge. Memoized per spec for the build's
        duration (the source file is immutable while bundling); the returned
        tuple is shared and must be treated read-only by callers.
        """
        cached = self._exports_cache.get(spec)
        if cached is not None:
            return cached
        src = self.read_source(spec)
        if src is None:
            result: tuple[set[str], bool] = (set(), False)
        else:
            result = _extract_esm_exports(
                src,
                source_map=self,
                importing_specifier=spec,
                _exports_cache=self._star_cache,
            )
        self._exports_cache[spec] = result
        return result


def _bridge_shim_source(
    specifier: str,
    kinds: set[str],
    src_names: set[str],
    has_default: bool,
) -> tuple[str, bool]:
    """Build the bridge shim JS for one specifier.

    The default-export block is emitted UNCONDITIONALLY — not only when the
    source has a default or a consumer requested one.  The runtime
    counterpart (``@web/core/module_bridge.buildBridgeModuleSource``) cannot
    know consumer kinds, so it always emits the block; the two generators
    must produce the same shape for a server bridge attachment and a
    client-built ``data:`` bridge to be interchangeable.  For a module with
    no default export ``_m?.default`` is ``undefined`` and ``_d`` falls back
    to the namespace itself — esbuild's ESM-default interop.  (The old
    conditional emission could even produce a DUPLICATE ``export default``
    — a SyntaxError — for an unreadable source consumed via ``import *``:
    ``__star__`` triggered the first branch and the star fallback appended
    a second one.)

    Returns ``(shim_js, is_star_fallback)`` — ``is_star_fallback`` is True
    when the export surface is empty (source couldn't be read) and no
    default was requested; the shim then carries only the default/namespace
    fallback.  The flag feeds the ``star_fallback`` telemetry counter in
    ``esm_bridges``.

    CONTRACT (mirrored in ``@web/core/module_bridge``): each
    ``export const <name> = _m?.<name>`` line is a VALUE SNAPSHOT taken when
    the bridge evaluates — ES-module live bindings cannot be reproduced by a
    generated module.  Bridged modules therefore must not rely on mutable
    ``export let`` bindings reassigned after load; lazily-loaded values must
    be exposed through a stable ``const`` facade instead (see
    ``makeLazyFacade`` in ``@web/core/module_bridge`` and its use in
    ``@web/core/lib/chartjs``/``fullcalendar`` and ``@web/core/utils/pdfjs``).
    """
    # Shim target: the import map entry for this specifier.  The
    # runtime looks the module up in ``odoo.loader.modules``; the
    # key there is set by ``registerNativeModules`` with the
    # exact specifier string.
    lines = [
        f"const _m = odoo.loader.modules.get({json.dumps(specifier)});",
        # Covers all consumers:
        #  * real default export → _m.default exists
        #  * consumer imports ``import X from`` → fall back to _m
        #    itself (matches esbuild's ESM-default interop)
        #  * ``import * as`` → the namespace IS _m
        "const _d = _m?.default ?? _m;",
        "export default _d;",
    ]
    lines.extend(f"export const {name} = _m?.{name};" for name in sorted(src_names))
    is_star_fallback = not src_names and not has_default and "__default__" not in kinds
    return "\n".join(lines), is_star_fallback
