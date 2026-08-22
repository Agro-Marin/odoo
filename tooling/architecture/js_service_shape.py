import argparse
import contextlib
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ADR = "0021"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="js_service_shape")
WEB_SRC = ROOT / "addons" / "web" / "static" / "src"

GOVERNED_ADDONS = ("web", "mail", "account", "stock")
DEFAULT_ADDON = "web"


def addon_src(addon: str = DEFAULT_ADDON):
    return (
        WEB_SRC
        if addon == DEFAULT_ADDON
        else ROOT / "addons" / addon / "static" / "src"
    )


ANALYZER = Path(__file__).with_suffix(".mjs")

LARGE = 80


@dataclass(frozen=True)
class Service:
    file: str
    service: str
    shape: str
    lines: int


def iter_service_files(web_src: Path | None = None) -> list[Path]:

    web_src = WEB_SRC if web_src is None else web_src
    if not web_src.is_dir():
        return []
    needle = 'registry.category("services")'
    out = []
    for path in sorted(web_src.rglob("*.js")):
        try:
            if needle in path.read_text(encoding="utf8", errors="replace"):
                out.append(path)
        except OSError:  # pragma: no cover
            continue
    return out


def analyse(files: list[Path]) -> list[Service]:
    if not files:
        return []
    proc = subprocess.run(
        ["node", str(ANALYZER), *[str(f) for f in files]],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"service-shape analyzer failed: {proc.stderr.strip()}")
    services = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        rel = Path(raw["file"])
        with contextlib.suppress(ValueError):
            rel = rel.resolve().relative_to(WEB_SRC.resolve())
        services.append(
            Service(rel.as_posix(), raw["service"], raw["shape"], raw["lines"])
        )
    return sorted(services, key=lambda s: (-s.lines, s.service))


def literals(services: list[Service]) -> list[Service]:
    return [s for s in services if s.shape == "literal"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", action="store_true", help="print the budget only")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--addon",
        default=DEFAULT_ADDON,
        choices=GOVERNED_ADDONS,
        help="which addon's static/src to scan (default: web)",
    )
    args = parser.parse_args(argv)

    src = addon_src(args.addon)
    files = iter_service_files(src)
    if not files:
        parser.error(f"no service registrations under {src} — the scan reached nothing")

    services = analyse(files)
    if not services:
        parser.error("analyzer returned no services — refusing to report a pass")

    lit = literals(services)
    unknown = [s for s in services if s.shape == "unknown"]
    instances = [s for s in services if s.shape == "instance"]
    big = [s for s in lit if s.lines > LARGE]

    if args.count:
        print(len(lit))
        return 0
    if args.json:
        print(
            json.dumps(
                {
                    "literal": [asdict(s) for s in lit],
                    "instance": [asdict(s) for s in instances],
                    "unknown": [asdict(s) for s in unknown],
                    "count": len(lit),
                    "services_scanned": len(services),
                },
                indent=2,
            )
        )
        return 0

    print("JS service-shape budget (start() returns an instance, not a literal)")
    print("=" * 72)
    print(f"\n{len(big)} literal start() over {LARGE} lines — do these first:\n")
    for s in big:
        print(f"  {s.lines:5d}  {s.service:<22}{s.file}")
    print(f"\n  subtotal: {sum(s.lines for s in big)} lines behind a closure wall")

    print(
        f"\n{len(instances)} service(s) already instance-shaped — the pattern to copy:\n"
    )
    for s in instances:
        print(f"  {s.lines:5d}  {s.service:<22}{s.file}")

    if unknown:
        print(f"\n{len(unknown)} undecidable, reported not counted:\n")
        for s in unknown:
            print(f"  {s.lines:5d}  {s.service:<22}{s.file}")

    print("-" * 72)
    print(f"\n{len(lit)} of {len(services)} services return an object literal")
    print("\nRatchet this number:")
    suffix = "" if args.addon == DEFAULT_ADDON else f" --addon {args.addon}"
    name = (
        "jsserviceshape"
        if args.addon == DEFAULT_ADDON
        else f"jsserviceshape_{args.addon}"
    )
    print(f"  python tooling/architecture/js_service_shape.py{suffix} --count \\")
    print(f"      | xargs python tooling/ratchet/ratchet.py {name} --count")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
