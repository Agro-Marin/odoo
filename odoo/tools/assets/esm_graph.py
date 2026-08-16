import functools
import logging
import posixpath
import re
from collections import deque
from collections.abc import Collection, Iterable, Mapping
from pathlib import Path

from odoo.libs.asset_log import get_asset_logger, log_event
from odoo.tools.assets.constants import DOTTED_ASSET_EXTENSIONS as EXTENSIONS
from odoo.tools.assets.esm_lexer import lex_module
from odoo.tools.files import file_open, file_path
from odoo.tools.json import scriptsafe as json

_logger = logging.getLogger(__name__)
_bridge_log = get_asset_logger("bridge")


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
    return _ODOO_MODULE_RE.search(content[:500])


def is_native_module(content: str) -> bool:
    result = _parse_odoo_module_header(content)
    return bool(result and result["native"])


def is_odoo_module(url: str, content: str) -> bool:
    result = _parse_odoo_module_header(content)
    if result and (result["ignore"] or result["native"]):
        return False
    parts = url.split("/") if url else []
    if len(parts) > 1:
        addon = parts[1]
        if url.startswith((f"/{addon}/static/src", f"/{addon}/static/tests")):
            return True
    return bool(result)


def url_to_module_path(url: str) -> str:
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


_MODULE_SYNTAX_RE = re.compile(
    r"""^\s*(?:import\s*(?:["'{*]|\w+\s*(?:,|from\b))|export\b)""",
    re.MULTILINE,
)

_JS_OPAQUE_RE = re.compile(r"/\*.*?\*/|`[^`]*`", re.DOTALL)


def has_module_syntax(content: str) -> bool:
    return bool(_MODULE_SYNTAX_RE.search(_JS_OPAQUE_RE.sub("", content)))


@functools.lru_cache(maxsize=16384)
def _cached_module_classification(
    url: str, filename: str, last_modified: float
) -> bool:
    try:
        with file_open(filename, "rb", filter_ext=EXTENSIONS) as fp:
            content = fp.read(512).decode("utf-8", errors="ignore")
    except OSError, ValueError:
        return False
    return is_native_module(content) or is_odoo_module(url, content)


_ESM_EXPORT_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        "decl",
        r"export\s+(?:const|let|var|function\*?|class|async\s+function\*?)\s+(\w+)",
    ),
    ("destructured", r"export\s+(?:const|let|var)\s*\{([^}]+)\}\s*="),
    ("list_from", r'export\s*\{([^}]+)\}\s*from\s*["\']([^"\']+)["\']'),
    ("list", r"export\s*\{([^}]+)\}"),
    ("star_from", r'export\s*\*\s*from\s*["\']([^"\']+)["\']'),
    ("ns_from", r'export\s*\*\s*as\s+(\w+)\s*from\s*["\']([^"\']+)["\']'),
)
_ESM_EXPORT_PATTERNS_COMPILED: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (kind, re.compile(pattern)) for kind, pattern in _ESM_EXPORT_PATTERNS
)
_ESM_EXPORT_DEFAULT_RE_SRC = (
    r"export\s+default(?:\s+(?:async\s+)?(?:function\*?|class)(?:\s+\w+)?)?"
)
_ESM_EXPORT_DEFAULT_RE = re.compile(_ESM_EXPORT_DEFAULT_RE_SRC)

_IMPORT_ANY_RE = re.compile(
    r"import(?:"
    r"\s*(?P<named>\{[^}]+\})\s*"
    r"|\s*(?P<star>\*\s*as\s+\w+)\s+"
    r"|\s+(?P<mixed>\w+\s*,\s*(?:\{[^}]+\}|\*\s*as\s+\w+))\s*"
    r"|\s+(?P<default>\w+)\s+"
    r")from\s*"
    r"""["'](?P<spec>@[^"']+)["']"""
    r"""|import\s*["'](?P<side>@[^"']+)["']"""
)

_TRANSITIVE_IMPORT_RE = re.compile(
    r"(?<![\w$.])(?:import|export)\s*"
    r"[\w$*{},\s]{0,400}?"
    r"\bfrom\s*"
    r"""["'](?P<spec>[^"'\n]+)["']"""
    r"""|(?<![\w$.])import\s*["'](?P<side>[^"'\n]+)["']"""
)


def _scan_import_specifiers(src: str) -> set[str]:
    specs: set[str] = set()
    lexed = lex_module(src)
    if lexed is not None:
        specs.update(imp["n"] for imp in lexed["imports"])
        specs.update(lexed.get("starFrom") or ())
    specs.update(
        match.group("spec") or match.group("side")
        for match in _TRANSITIVE_IMPORT_RE.finditer(src)
    )
    return specs


def find_escaping_relative_imports(
    modules: Iterable,
) -> list[tuple[str, str, str]]:
    modules = list(modules)
    member_specs = {m.module_path for m in modules}
    member_specs.update(
        m.module_path + "/index"
        for m in modules
        if getattr(m, "url", "").endswith("/index.js")
    )
    escapes: list[tuple[str, str, str]] = []
    for module in modules:
        src = module.raw_content
        lexed = lex_module(src)
        if lexed is not None:
            specs = {imp["n"] for imp in lexed["imports"]}
            specs.update(lexed.get("starFrom") or ())
        else:
            specs = {
                match.group("spec") or match.group("side")
                for match in _TRANSITIVE_IMPORT_RE.finditer(src)
            }
        for spec in sorted(specs):
            if not spec.startswith("."):
                continue
            resolved = _resolve_export_specifier(
                module.module_path, spec, getattr(module, "url", "") or None
            )
            if resolved and resolved not in member_specs:
                escapes.append((module.module_path, spec, resolved))
    return escapes


def discover_transitive_import_specifiers(
    seed_specifiers: Iterable[str],
    known_specifiers: Collection[str],
    ext_libs: Mapping[str, str],
    lib_candidates: Mapping[str, tuple[str, ...]],
    bundle_name: str = "",
) -> set[str]:
    resolver = _BridgeExportResolver(ext_libs, lib_candidates, bundle_name)
    known = set(known_specifiers) | set(ext_libs) | {"@odoo/owl"}
    discovered: set[str] = set()
    queue: deque[str] = deque(seed_specifiers)
    scanned: set[str] = set(queue)
    while queue:
        spec = queue.popleft()
        src = resolver.read_source(spec)
        if src is None:
            continue
        for target in _scan_import_specifiers(src):
            if target.startswith("."):
                abs_spec = _resolve_export_specifier(
                    spec, target, resolver.resolve_url(spec)
                )
                if abs_spec and abs_spec not in scanned:
                    scanned.add(abs_spec)
                    queue.append(abs_spec)
                continue
            if not target.startswith("@") or target in known or target in discovered:
                continue
            discovered.add(target)
            scanned.add(target)
            queue.append(target)
    if discovered:
        log_event(
            _bridge_log,
            logging.DEBUG,
            "transitive_specifiers",
            bundle=bundle_name,
            seeds=len(scanned),
            discovered=len(discovered),
        )
    return discovered


def _source_map_url(source_map: object, spec: str | None) -> str | None:
    resolve = getattr(source_map, "resolve_url", None)
    return resolve(spec) if callable(resolve) and spec else None


def _resolve_relative_url(importing_url: str, target_path: str) -> str | None:
    joined = posixpath.normpath(
        posixpath.join(posixpath.dirname(importing_url), target_path)
    )
    try:
        return url_to_module_path(joined)
    except ValueError:
        return None


def _resolve_export_specifier(
    importing_specifier: str | None,
    target_path: str,
    importing_url: str | None = None,
) -> str | None:
    if not target_path.startswith("."):
        return target_path.removesuffix(".js")
    if importing_url:
        resolved = _resolve_relative_url(importing_url, target_path)
        if resolved is not None:
            return resolved
    if not importing_specifier:
        return None
    parent_parts = importing_specifier.rsplit("/", 1)
    if len(parent_parts) < 2:
        return None
    base = parent_parts[0]
    rel_parts = target_path.split("/")
    while rel_parts and rel_parts[0] in (".", ".."):
        if rel_parts[0] == "..":
            base = base.rsplit("/", 1)[0] if "/" in base else base
        rel_parts.pop(0)
    resolved = f"{base}/{'/'.join(rel_parts)}" if rel_parts else base
    return resolved.removesuffix(".js")


def _extract_esm_exports(
    src: str,
    source_map: dict[str, str] | None = None,
    importing_specifier: str | None = None,
    importing_url: str | None = None,
    _visited: set[str] | None = None,
    _exports_cache: dict[str, set[str]] | None = None,
) -> tuple[set[str], bool]:
    visited = _visited if _visited is not None else set()
    names: set[str] = set()

    def expand_star(raw_target: str) -> None:
        target_spec = _resolve_export_specifier(
            importing_specifier, raw_target, importing_url
        )
        if _exports_cache is not None and target_spec in _exports_cache:
            names.update(_exports_cache[target_spec])
            return
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
            importing_url=_source_map_url(source_map, target_spec),
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
                for raw in match.group(1).split(","):
                    token = raw.strip().split(" as ")[-1]
                    if ":" in token:
                        token = token.rsplit(":", 1)[-1]
                    if "=" in token:
                        token = token.split("=", 1)[0]
                    token = token.strip()
                    if token and token != "default":
                        names.add(token)
            elif kind == "ns_from":
                names.add(match.group(1))
            elif kind == "star_from":
                expand_star(match.group(1))
    has_default = bool(_ESM_EXPORT_DEFAULT_RE.search(src))
    return names, has_default


class _BridgeExportResolver:
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
        self._cache: dict[str, str | None] = {}
        self._exports_cache: dict[str, tuple[set[str], bool]] = {}
        self._star_cache: dict[str, set[str]] = {}

    def resolve_url(self, spec: str) -> str | None:
        if spec in self._ext_libs:
            return self._ext_libs[spec]
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
                if rel.endswith(".js"):
                    fpath = file_path(rel[:-3] + "/index.js")
                else:
                    raise
            src = Path(fpath).read_text(encoding="utf-8")
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
        src = self.read_source(key)
        return src if src is not None else default

    def source_exports(self, spec: str) -> tuple[set[str], bool]:
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
                importing_url=self.resolve_url(spec),
                _exports_cache=self._star_cache,
            )
        self._exports_cache[spec] = result
        return result


_VALID_EXPORT_NAME = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*\Z")


def _bridge_shim_source(
    specifier: str,
    kinds: set[str],
    src_names: set[str],
    has_default: bool,
) -> tuple[str, bool]:
    """Emit the shim that re-publishes one specifier from ``odoo.loader.modules``.

    The bindings are ``let`` re-exported by name, never ``const`` and never
    ``export default <expr>``, and that is the whole point: both of those
    snapshot at evaluation. A shim reached before its producer registered bound
    ``undefined`` for every export and kept it, permanently, because an
    import-map entry cannot be re-mapped once the document holds it — so the
    consumer had no second chance either.

    ``export { _d as default }`` IS a live binding where ``export default _d``
    is not; the spelling matters.

    ``_s`` runs once at evaluation and again on the loader's ``registered``
    event, then unsubscribes. Consumers that read at use time
    (``registry.category(...)``, ``_t(...)``) pick the value up. A consumer that
    reads at module scope — ``class X extends Y`` — still cannot, which is why
    `TestDynamicBundleIntegrity` refuses a lazy bundle whose producer the page
    never registers at all: this makes ordering survivable, not absence.
    """
    names = [
        name
        for name in sorted(src_names)
        if name != "default" and _VALID_EXPORT_NAME.match(name)
    ]
    locals_ = ["_d", *(f"_e{i}" for i in range(len(names)))]
    lines = [f"let {', '.join(locals_)};"]
    lines.append("function _s() {")
    lines.append(f"  const _m = odoo.loader.modules.get({json.dumps(specifier)});")
    lines.append("  if (_m === undefined) { return; }")
    lines.append("  _d = _m.default ?? _m;")
    lines.extend(f"  _e{i} = _m.{name};" for i, name in enumerate(names))
    lines.append('  odoo.loader.bus.removeEventListener("registered", _s);')
    lines.append("}")
    lines.append("_s();")
    lines.append('odoo.loader.bus.addEventListener("registered", _s);')
    exported = ["_d as default", *(f"_e{i} as {n}" for i, n in enumerate(names))]
    lines.append("export { " + ", ".join(exported) + " };")
    is_star_fallback = not src_names and not has_default and "__default__" not in kinds
    return "\n".join(lines), is_star_fallback
