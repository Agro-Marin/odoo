import argparse
import json
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ADR = "0021"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="js_patch_blind_facade")
WEB_SRC = ROOT / "addons" / "web" / "static" / "src"
ACORN = ROOT / "node_modules" / "acorn" / "dist" / "acorn.mjs"

SERVICE_MARKER = 'category("services").add'

ANALYZER_JS = r"""
import { parse } from "%(acorn)s";
import { readFileSync } from "fs";

const walk = (node, fn, stopAtFunctions = false, depth = 0) => {
    if (!node || typeof node !== "object") return;
    if (stopAtFunctions && depth > 0 && /Function(Expression|Declaration)$/.test(node.type)) return;
    fn(node);
    for (const key in node) {
        const value = node[key];
        if (Array.isArray(value)) value.forEach((c) => walk(c, fn, stopAtFunctions, depth + 1));
        else if (value && typeof value === "object" && value.type) walk(value, fn, stopAtFunctions, depth + 1);
    }
};

const out = [];
for (const file of JSON.parse(readFileSync(process.argv[2], "utf8"))) {
    const src = readFileSync(file, "utf8");
    let ast;
    try {
        ast = parse(src, { ecmaVersion: "latest", sourceType: "module", locations: true });
    } catch (e) {
        out.push({ file, parseError: String(e.message) });
        continue;
    }
    // Every `start(...)` method of a service-definition object literal.
    const starts = [];
    walk(ast, (n) => {
        if (n.type === "Property" && (n.key?.name === "start" || n.key?.value === "start")
            && n.value?.type === "FunctionExpression") starts.push(n.value);
    });
    for (const fn of starts) {
        // The facade: the object `start` returns, either as a literal or via an
        // identifier bound to a literal in the same scope.
        let facade = null;
        const consts = new Map();
        walk(fn.body, (n) => {
            if (n.type === "VariableDeclarator" && n.id?.type === "Identifier"
                && n.init?.type === "ObjectExpression") consts.set(n.id.name, n.init);
        }, true);
        walk(fn.body, (n) => {
            if (n.type !== "ReturnStatement" || !n.argument) return;
            if (n.argument.type === "ObjectExpression") facade = n.argument;
            else if (n.argument.type === "Identifier" && consts.has(n.argument.name))
                facade = consts.get(n.argument.name);
        }, true);
        if (!facade) continue;
        // Published name -> the closure identifier backing it (if shorthand).
        const published = new Map();
        for (const p of facade.properties) {
            if (p.type !== "Property") continue;
            const name = p.key?.name ?? p.key?.value;
            if (!name) continue;
            published.set(name, p.value?.type === "Identifier" ? p.value.name : null);
        }
        // Bare-identifier calls inside start() that hit a published name.
        const hits = new Map();
        walk(fn.body, (n) => {
            if (n.type !== "CallExpression" || n.callee?.type !== "Identifier") return;
            for (const [name, backing] of published) {
                if (n.callee.name === name || (backing && n.callee.name === backing)) {
                    if (!hits.has(name)) hits.set(name, []);
                    hits.get(name).push(n.loc.start.line);
                }
            }
        });
        for (const [method, lines] of hits) out.push({ file, method, lines });
    }
}
process.stdout.write(JSON.stringify(out));
"""


@dataclass(frozen=True, order=True)
class Violation:
    file: str
    method: str
    lines: tuple[int, ...]

    def __str__(self) -> str:
        at = ", ".join(f":{n}" for n in self.lines)
        return f"  {self.file}  {self.method}() called via closure at {at}"


def _service_files(src: Path) -> list[Path]:
    return sorted(
        p
        for p in src.rglob("*.js")
        if SERVICE_MARKER in p.read_text(encoding="utf-8", errors="replace")
    )


def measure(src: Path | None = None, acorn: Path | None = None) -> list[Violation]:

    src = WEB_SRC if src is None else src
    acorn = ACORN if acorn is None else acorn
    if not src.is_dir():
        raise RuntimeError(f"source tree not found: {src}")
    if not acorn.is_file():
        raise RuntimeError(f"acorn not found at {acorn} (run `npm ci`)")
    files = _service_files(src)
    if not files:
        raise RuntimeError(f"no service definitions found under {src}")

    with tempfile.TemporaryDirectory() as tmp:
        manifest = Path(tmp) / "files.json"
        manifest.write_text(json.dumps([str(p) for p in files]), encoding="utf-8")
        script = Path(tmp) / "analyze.mjs"
        script.write_text(ANALYZER_JS % {"acorn": acorn.as_uri()}, encoding="utf-8")
        proc = subprocess.run(
            ["node", str(script), str(manifest)],
            capture_output=True,
            text=True,
            check=False,
        )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError(
            f"analyzer failed (exit {proc.returncode}): {proc.stderr[:400]}"
        )

    found: list[Violation] = []
    for entry in json.loads(proc.stdout):
        if "parseError" in entry:
            raise RuntimeError(
                f"parse failed for {entry['file']}: {entry['parseError']}"
            )
        found.append(
            Violation(
                file=str(Path(entry["file"]).relative_to(src)),
                method=entry["method"],
                lines=tuple(entry["lines"]),
            )
        )
    return sorted(found)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="CI mode: exit 1 on drift")
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        found = measure()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.count:
        print(len(found))
        return 0
    if args.json:
        print(json.dumps([asdict(v) for v in found], indent=2))
        return 0

    print("Patch-blind service facades (web/static/src)")
    print("=" * 72)
    if not found:
        print("\nEvery service routes its own callers through its facade. ✓\n")
        return 0
    for v in found:
        print(v)
    print("-" * 72)
    print(f"\n{len(found)} patch-blind facade method(s)")
    print(
        "\nA downstream patch of these methods applies to external consumers but\n"
        "NOT to the call sites above. Name the facade and route them through it:\n"
        "    const xServiceApi = { ... };\n"
        "    ... xServiceApi.method() ...\n"
        "    return xServiceApi;"
    )
    return 1 if args.check else 0


if __name__ == "__main__":
    sys.exit(main())
