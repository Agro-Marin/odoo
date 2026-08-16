import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root
from js_imports import strip_comments

ADR = "0019"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="js_registry_layering")
WEB_SRC = ROOT / "addons" / "web" / "static" / "src"

LAYER_ORDER: tuple[str, ...] = (
    "core",
    "ui",
    "components",
    "model",
    "fields",
    "search",
    "views",
    "webclient",
)
RANK = {name: i for i, name in enumerate(LAYER_ORDER)}

PRODUCER_RE = re.compile(
    r'registry\s*\.\s*category\(\s*"services"\s*\)\s*\.\s*add\(\s*"([^"]+)"'
)
CONSUMER_RES = (
    re.compile(r'useService\(\s*"([^"]+)"\s*\)'),
    re.compile(r"\benv\s*\.\s*services\s*\.\s*([A-Za-z_$][\w$]*)"),
    re.compile(r'\bservices\s*\[\s*"([^"]+)"\s*\]'),
)

CATEGORY_ADD_RE = re.compile(
    r'registry\s*\.\s*category\(\s*"([^"]+)"\s*\)\s*\.\s*add\(\s*"([^"]+)"'
)
CATEGORY_GET_RE = re.compile(
    r'registry\s*\.\s*category\(\s*"([^"]+)"\s*\)\s*\.\s*get\(\s*"([^"]+)"'
)
CATEGORY_BIND_RE = re.compile(
    r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*"
    r'registry\s*\.\s*category\(\s*"([^"]+)"\s*\)'
)
CATEGORY_EXPORT_BIND_RE = re.compile(
    r"export\s+const\s+([A-Za-z_$][\w$]*)\s*=\s*"
    r'registry\s*\.\s*category\(\s*"([^"]+)"\s*\)'
)
NAMED_IMPORT_RE = re.compile(r'import\s*\{([^}]*)\}\s*from\s*"([^"]+)"')


@dataclass(frozen=True)
class Known:
    module: str
    service: str
    consumer: str
    producer: str


@dataclass(frozen=True)
class KnownKeyed:
    module: str
    category: str
    key: str
    consumer: str
    producer: str


@dataclass
class Inversion:
    module: str
    service: str
    consumer_layer: str
    producer_layer: str
    producer: str
    lineno: int
    contract: str = "services"


KNOWN_INVERSIONS: tuple[Known, ...] = (
    Known("core/action_port.js", "action", "core", "webclient"),
    Known("core/utils/hooks.js", "dialog", "core", "ui"),
    Known("core/utils/hooks.js", "ui", "core", "ui"),
    Known("core/utils/files.js", "notification", "core", "ui"),
    Known("core/file_upload/file_handler.js", "notification", "core", "ui"),
    Known("fields/relational/x2many_dialog.js", "view", "fields", "views"),
    Known("search/with_search/with_search.js", "view", "search", "views"),
)

KNOWN_KEYED_INVERSIONS: tuple[KnownKeyed, ...] = (
    KnownKeyed(
        "fields/relational/x2many/x2many_field.js", "views", "kanban", "fields", "views"
    ),
    KnownKeyed(
        "fields/relational/x2many/x2many_field.js", "views", "list", "fields", "views"
    ),
    KnownKeyed(
        "fields/relational/x2many_dialog.js", "views", "form", "fields", "views"
    ),
    KnownKeyed(
        "fields/specialized/user_groups/res_user_group_ids_field.js",
        "views",
        "form",
        "fields",
        "views",
    ),
    KnownKeyed(
        "core/record_dialog_port.js", "dialogs", "select_create", "core", "views"
    ),
    KnownKeyed("core/record_dialog_port.js", "dialogs", "form_view", "core", "views"),
    KnownKeyed(
        "fields/relational/x2many/x2many_field.js",
        "shared_components",
        "ViewButton",
        "fields",
        "views",
    ),
    KnownKeyed(
        "fields/relational/x2many/x2many_field.js",
        "shared_components",
        "computeViewClassName",
        "fields",
        "views",
    ),
    KnownKeyed(
        "fields/relational/x2many_dialog.js",
        "shared_components",
        "ViewButton",
        "fields",
        "views",
    ),
    KnownKeyed(
        "fields/relational/x2many_dialog.js",
        "shared_components",
        "computeViewClassName",
        "fields",
        "views",
    ),
    KnownKeyed(
        "fields/relational/x2many_dialog.js",
        "shared_components",
        "useViewButtons",
        "fields",
        "views",
    ),
    KnownKeyed(
        "fields/relational/x2many_dialog.js",
        "shared_components",
        "useFormViewInDialog",
        "fields",
        "views",
    ),
    KnownKeyed(
        "fields/relational/x2many_dialog.js",
        "shared_components",
        "executeButtonCallback",
        "fields",
        "views",
    ),
    KnownKeyed(
        "fields/relational/x2many_dialog.js",
        "shared_components",
        "loadSubViews",
        "fields",
        "views",
    ),
)


def layer_of(rel: str) -> str | None:
    top = rel.split("/", maxsplit=1)[0]
    return top if top in RANK else None


def iter_source_files() -> list[Path]:
    if not WEB_SRC.is_dir():
        return []
    return [f for f in sorted(WEB_SRC.rglob("*.js")) if "__pycache__" not in f.parts]


def resolve(files: list[Path]) -> tuple[dict[str, str], list[tuple[str, str, int]]]:
    producers: dict[str, str] = {}
    consumers: list[tuple[str, str, int]] = []
    for path in files:
        rel = path.relative_to(WEB_SRC).as_posix()
        try:
            src = strip_comments(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, OSError) as exc:  # pragma: no cover
            print(f"warning: could not read {path}: {exc}", file=sys.stderr)
            continue
        for m in PRODUCER_RE.finditer(src):
            producers[m.group(1)] = rel
        for pattern in CONSUMER_RES:
            consumers.extend(
                (rel, m.group(1), src[: m.start()].count("\n") + 1)
                for m in pattern.finditer(src)
            )
    return producers, consumers


def spec_to_rel(specifier: str) -> str | None:
    if not specifier.startswith("@web/"):
        return None
    return specifier[len("@web/") :] + ".js"


def imported_category_aliases(
    src: str, exported: dict[tuple[str, str], str]
) -> dict[str, str]:

    aliases: dict[str, str] = {}
    for m in NAMED_IMPORT_RE.finditer(src):
        source = spec_to_rel(m.group(2))
        if source is None:
            continue
        for clause in m.group(1).split(","):
            parts = clause.split()
            if not parts:
                continue
            name, local = parts[0], parts[-1]
            category = exported.get((source, name))
            if category is not None:
                aliases[local] = category
    return aliases


def resolve_keyed(
    files: list[Path],
) -> tuple[dict[tuple[str, str], str], list[tuple[str, str, str, int]]]:
    registrars: dict[tuple[str, str], str] = {}
    lookups: list[tuple[str, str, str, int]] = []
    texts: list[tuple[str, str]] = []
    exported: dict[tuple[str, str], str] = {}
    for path in files:
        rel = path.relative_to(WEB_SRC).as_posix()
        try:
            src = strip_comments(path.read_text(encoding="utf-8"))
        except UnicodeDecodeError, OSError:  # pragma: no cover
            continue
        texts.append((rel, src))
        for m in CATEGORY_ADD_RE.finditer(src):
            registrars[(m.group(1), m.group(2))] = rel
        for m in CATEGORY_EXPORT_BIND_RE.finditer(src):
            exported[(rel, m.group(1))] = m.group(2)

    for rel, src in texts:
        for local, category in imported_category_aliases(src, exported).items():
            for m in re.finditer(re.escape(local) + r'\s*\.\s*add\(\s*"([^"]+)"', src):
                registrars[(category, m.group(1))] = rel

    for rel, src in texts:
        lookups.extend(
            (rel, m.group(1), m.group(2), src[: m.start()].count("\n") + 1)
            for m in CATEGORY_GET_RE.finditer(src)
        )
        local_bindings = {
            bind.group(1): bind.group(2) for bind in CATEGORY_BIND_RE.finditer(src)
        }
        for local, category in (
            local_bindings | imported_category_aliases(src, exported)
        ).items():
            lookups.extend(
                (rel, category, m.group(1), src[: m.start()].count("\n") + 1)
                for m in re.finditer(
                    re.escape(local) + r'\s*\.\s*get\(\s*"([^"]+)"', src
                )
            )
    return registrars, lookups


def check(files: list[Path] | None = None) -> tuple[list[Inversion], list[Inversion]]:
    files = files if files is not None else iter_source_files()
    new: list[Inversion] = []
    known: list[Inversion] = []

    producers, consumers = resolve(files)
    pinned = {(k.module, k.service, k.consumer, k.producer) for k in KNOWN_INVERSIONS}
    seen: set[tuple[str, str]] = set()
    for rel, service, lineno in consumers:
        producer = producers.get(service)
        if producer is None or producer == rel or (rel, service) in seen:
            continue
        c_layer, p_layer = layer_of(rel), layer_of(producer)
        if c_layer is None or p_layer is None or RANK[c_layer] >= RANK[p_layer]:
            continue
        seen.add((rel, service))
        inv = Inversion(rel, service, c_layer, p_layer, producer, lineno, "services")
        bucket = known if (rel, service, c_layer, p_layer) in pinned else new
        bucket.append(inv)

    registrars, lookups = resolve_keyed(files)
    pinned_keyed = {
        (k.module, k.category, k.key, k.consumer, k.producer)
        for k in KNOWN_KEYED_INVERSIONS
    }
    seen_keyed: set[tuple[str, str, str]] = set()
    for rel, category, key, lineno in lookups:
        registrar = registrars.get((category, key))
        if registrar is None or registrar == rel or (rel, category, key) in seen_keyed:
            continue
        c_layer, p_layer = layer_of(rel), layer_of(registrar)
        if c_layer is None or p_layer is None or RANK[c_layer] >= RANK[p_layer]:
            continue
        seen_keyed.add((rel, category, key))
        inv = Inversion(
            rel,
            f"{category}:{key}",
            c_layer,
            p_layer,
            registrar,
            lineno,
            "keyed-lookup",
        )
        bucket = (
            known if (rel, category, key, c_layer, p_layer) in pinned_keyed else new
        )
        bucket.append(inv)
    return new, known


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="CI mode: exit 1 on any NEW inversion"
    )
    parser.add_argument("--count", action="store_true", help="print the total only")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    files = iter_source_files()
    if not files:
        parser.error(f"no JS sources under {WEB_SRC} — the scan reached nothing")

    new, known = check(files)

    if args.count:
        print(len(new) + len(known))
    elif args.json:
        print(
            json.dumps(
                {
                    "new": [i.__dict__ for i in new],
                    "known": [i.__dict__ for i in known],
                    "files_scanned": len(files),
                },
                indent=2,
            )
        )
    else:
        print("JS registry-mediated layering check (the half imports don't show)")
        print("=" * 68)
        by_service: dict[str, int] = {}
        for inv in new + known:
            by_service[inv.service] = by_service.get(inv.service, 0) + 1
        for service, n in sorted(by_service.items(), key=lambda kv: -kv[1]):
            print(f"  {n:>3}  {service}")
        print("-" * 68)
        if new:
            print(f"\n{len(new)} NEW inversion(s) — these fail the gate:\n")
            for inv in new:
                print(f"  {inv.module}:{inv.lineno}")
                print(
                    f"      {inv.consumer_layer} consumes '{inv.service}' "
                    f"produced by {inv.producer_layer} ({inv.producer})"
                )
        else:
            print("\nNo new registry layer inversions. ✓")
        if known:
            print(f"\n{len(known)} pinned inversion(s) (tracked debt):\n")
            for inv in known:
                print(
                    f"  {inv.module}:{inv.lineno}  {inv.consumer_layer} -> "
                    f"'{inv.service}' ({inv.producer_layer})"
                )
        print(f"\nFiles scanned: {len(files)}")
        print(f"New: {len(new)}   Pinned: {len(known)}")

    if args.check and new:
        print(f"\nFAILED: {len(new)} new registry layer inversion(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
