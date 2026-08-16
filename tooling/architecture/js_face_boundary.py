import argparse
import json
import sys
from pathlib import Path

from js_imports import collect_imports, collect_type_imports

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ADR = "0020"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="js_face_boundary")
WEB = ROOT / "addons" / "web"
WEB_SRC = WEB / "static" / "src"

CONSUMER_ROOTS = (
    ROOT,
    ROOT.parent / "enterprise",
    ROOT.parent / "agromarin",
    ROOT.parent / "design-themes",
)

KNOWN_VIOLATIONS: dict[str, str] = {}

TYPE_REACHES_ARE_VIOLATIONS = False


def faced_directories(web_src: Path = WEB_SRC) -> set[str]:

    faced = set()
    for path in web_src.rglob("*"):
        if not path.is_dir():
            continue
        if path.with_suffix(".js").is_file():
            faced.add(path.relative_to(web_src).as_posix())
    return faced


def _outermost_face(module_path: str, faced: set[str]) -> str | None:
    parts = module_path.split("/")
    for i in range(1, len(parts)):
        prefix = "/".join(parts[:i])
        if prefix in faced:
            return prefix
    return None


def _is_web_internal(path: Path, web_root: Path) -> bool:

    try:
        path.relative_to(web_root)
    except ValueError:
        return False
    return True


def _display(path: Path) -> str:
    for base in (ROOT.parent, ROOT):
        try:
            return path.relative_to(base).as_posix()
        except ValueError:
            continue
    return path.as_posix()


def measure(
    consumer_roots=CONSUMER_ROOTS, web_src: Path = WEB_SRC
) -> list[dict[str, object]]:

    return _reaches(consumer_roots, web_src, collect_imports)


def measure_type_reaches(
    consumer_roots=CONSUMER_ROOTS, web_src: Path = WEB_SRC
) -> list[dict[str, object]]:
    return _reaches(consumer_roots, web_src, collect_type_imports)


def _reaches(consumer_roots, web_src: Path, collect) -> list[dict[str, object]]:
    faced = faced_directories(web_src)
    if not faced:
        return []
    web_root = web_src.parent.parent
    violations = []
    for root in consumer_roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.js"):
            text = path.as_posix()
            if "/static/lib/" in text or "/node_modules/" in text:
                continue
            if _is_web_internal(path, web_root):
                continue
            try:
                source = path.read_text(encoding="utf8")
            except UnicodeDecodeError, OSError:
                continue
            for spec, line in collect(source):
                if not spec.startswith("@web/") or spec.startswith("@web/../"):
                    continue
                module_path = spec[len("@web/") :]
                face = _outermost_face(module_path, faced)
                if face is None:
                    continue
                violations.append(
                    {
                        "spec": spec,
                        "face": f"@web/{face}",
                        "consumer": _display(path),
                        "line": line,
                    }
                )
    return sorted(violations, key=lambda v: (v["spec"], v["consumer"], v["line"]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 on violations")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--list-faces", action="store_true", help="print the faced directories"
    )
    args = parser.parse_args(argv)

    if not WEB_SRC.is_dir():
        parser.error(f"no web source tree at {WEB_SRC}")

    faced = faced_directories()
    if not faced:
        parser.error(
            f"found no faced directory under {WEB_SRC} — the scan reached nothing"
        )

    if args.list_faces:
        for name in sorted(faced):
            print(f"@web/{name}")
        return 0

    violations = measure()
    new = [v for v in violations if v["spec"] not in KNOWN_VIOLATIONS]
    known = [v for v in violations if v["spec"] in KNOWN_VIOLATIONS]

    type_reaches = measure_type_reaches()

    if args.json:
        print(
            json.dumps(
                {
                    "faces": sorted(faced),
                    "new": new,
                    "known": known,
                    "type_reaches": type_reaches,
                },
                indent=2,
            )
        )
        return 1 if (new and args.check) else 0

    print("JS face-boundary check (drift-zero)")
    print("=" * 64)
    print(f"{len(faced)} faced directory/ies under addons/web/static/src")
    if new:
        print(f"\n[FAIL] {len(new)} import(s) reach past a face:")
        for v in new[:25]:
            print(f"    {v['consumer']}:{v['line']}")
            print(f"        {v['spec']}  — enter at {v['face']} instead")
        if len(new) > 25:
            print(f"    … and {len(new) - 25} more")
    print("-" * 64)
    if not new:
        print("\nEvery faced directory is entered at its face. ✓")
    if known:
        print(f"\n{len(known)} known violation(s) tolerated (tracked debt):")
        for v in known:
            print(f"  {v['spec']} — {KNOWN_VIOLATIONS[v['spec']]}")
    print(f"\nNew: {len(new)}   Known/tolerated: {len(known)}")

    if type_reaches:
        untyped = [
            v
            for v in type_reaches
            if not str(v["consumer"]).startswith(("odoo/", "addons/odoo/"))
        ]
        by_face: dict[str, int] = {}
        for v in type_reaches:
            by_face[str(v["face"])] = by_face.get(str(v["face"]), 0) + 1
        print("-" * 64)
        print(
            f"\nAdvisory — {len(type_reaches)} JSDoc type reference(s) name a module "
            f"behind {len(by_face)} face(s)."
        )
        print("Not violations: a type reference depends on nothing at runtime.")
        for face, count in sorted(by_face.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"  {count:3}  {face}")
        if untyped:
            print(
                f"\n  Of these, {len(untyped)} sit in a repo that is in NO type "
                f"program (no tsconfig, no symlink), so a rename behind the face"
            )
            print("  is caught by neither this gate nor tsc:")
            for v in untyped:
                print(f"    {v['consumer']}:{v['line']}")
                print(f"        {v['spec']}")

    return 1 if (new and args.check) else 0


if __name__ == "__main__":
    sys.exit(main())
