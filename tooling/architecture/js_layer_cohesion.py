import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from js_imports import imported_specifiers

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ADR = "0019"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="js_layer_cohesion")
WEB_STATIC = ROOT / "addons" / "web" / "static"

MAX_ISOLATED_FRACTION = 0.35

MIN_FILES = 8

EXEMPT_LAYERS = frozenset({"scss", "@types"})

KNOWN_LOW_COHESION: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Finding:
    contract: str
    path: str
    detail: str

    def __str__(self) -> str:
        return f"  {self.path:26s} {self.detail}"


def _resolve(spec: str, from_file: Path, src: Path) -> str | None:
    if spec.startswith("@web/"):
        target = src / spec[len("@web/") :]
    elif spec.startswith("."):
        target = (from_file.parent / spec).resolve()
    else:
        return None
    for candidate in (target, target.with_suffix(".js"), target / "index.js"):
        try:
            rel = candidate.relative_to(src)
        except ValueError:
            return None
        if candidate.is_file():
            return rel.as_posix()
    return None


def layer_stats(web_static: Path) -> dict[str, tuple[int, int]]:
    src = web_static / "src"
    connected: dict[str, set[str]] = {}
    owned: dict[str, list[str]] = {}
    for path in sorted(src.rglob("*.js")):
        rel = path.relative_to(src).as_posix()
        parts = rel.split("/")
        if len(parts) < 2 or parts[0] in EXEMPT_LAYERS:
            continue
        owned.setdefault(parts[0], []).append(rel)
        connected.setdefault(rel, set())
    for path in sorted(src.rglob("*.js")):
        rel = path.relative_to(src).as_posix()
        if rel not in connected:
            continue
        source = path.read_text(encoding="utf8", errors="replace")
        for spec in imported_specifiers(source):
            target = _resolve(spec, path, src)
            if target is None or target not in connected or target == rel:
                continue
            if target.split("/")[0] == rel.split("/")[0]:
                connected[rel].add(target)
                connected[target].add(rel)
    return {
        layer: (len(files), sum(1 for f in files if not connected[f]))
        for layer, files in sorted(owned.items())
    }


def find_drift(
    web_static: Path,
    known: frozenset[str] | None = None,
) -> tuple[list[Finding], list[Finding]]:

    known = KNOWN_LOW_COHESION if known is None else known
    new: list[Finding] = []
    seen: set[str] = set()
    for layer, (total, isolated) in layer_stats(web_static).items():
        if total < MIN_FILES:
            continue
        fraction = isolated / total
        if fraction <= MAX_ISOLATED_FRACTION:
            continue
        seen.add(layer)
        if layer not in known:
            new.append(
                Finding(
                    "isolated-fraction",
                    f"src/{layer}/",
                    f"{isolated}/{total} files ({fraction:.0%}) import no sibling "
                    f"— over {MAX_ISOLATED_FRACTION:.0%}; a namespace, not a layer",
                )
            )
    stale = [
        Finding(
            "stale-known",
            f"src/{layer}/",
            "now cohesive — remove from KNOWN_LOW_COHESION",
        )
        for layer in sorted(known - seen)
    ]
    return new, stale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 on findings")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--table", action="store_true", help="print every layer")
    parser.add_argument("--web-static", type=Path, default=WEB_STATIC)
    args = parser.parse_args(argv)

    src = args.web_static / "src"
    scanned = sum(1 for _ in src.rglob("*.js")) if src.is_dir() else 0
    if not scanned:
        parser.error(f"no JS sources under {src} — the scan reached nothing")

    foreign = args.web_static.resolve() != WEB_STATIC.resolve()
    new, stale = find_drift(args.web_static, frozenset() if foreign else None)

    if args.json:
        stats = {
            layer: {"files": t, "isolated": i, "fraction": round(i / t, 4)}
            for layer, (t, i) in layer_stats(args.web_static).items()
        }
        print(
            json.dumps(
                {
                    "layers": stats,
                    "new": [asdict(f) for f in new],
                    "stale": [asdict(f) for f in stale],
                },
                indent=2,
            )
        )
        return 1 if ((new or stale) and args.check) else 0

    print("JS layer-cohesion check (drift-zero)")
    if foreign:
        print(f"scanning {args.web_static} — foreign tree, pins not applied")
    print("=" * 64)
    if args.table:
        for layer, (total, isolated) in sorted(
            layer_stats(args.web_static).items(), key=lambda kv: -kv[1][1] / kv[1][0]
        ):
            mark = (
                " "
                if total < MIN_FILES
                else ("!" if isolated / total > MAX_ISOLATED_FRACTION else " ")
            )
            print(
                f" {mark} {layer:12s} {isolated:3d}/{total:<4d} {isolated / total:5.0%}"
            )
        print("-" * 64)
    status = f"{len(new)} new" if new else "0 new"
    print(f"[{'FAIL' if new else '  ok'}] isolated-fraction: {status}")
    for f in new:
        print(f)
    if stale:
        print(f"\n[FAIL] {len(stale)} pinned entr(y/ies) now COHESIVE — unpin them:")
        for f in stale:
            print(f)
    print("-" * 64)
    if not new and not stale:
        print("\nNo new cohesion drift. ✓")
    if not foreign:
        print(f"\nKnown/tolerated: {len(KNOWN_LOW_COHESION)} low-cohesion layer(s)")

    return 1 if ((new or stale) and args.check) else 0


if __name__ == "__main__":
    sys.exit(main())
