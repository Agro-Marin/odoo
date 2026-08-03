"""Patch-blind facade gate: a service's own callers must go through its facade.

Odoo services are overwhelmingly written as a closure that returns an object
literal (~35 of 38 in ``addons/web/static/src``)::

    start(env, { hotkey }) {
        function openMainPalette(...) { ... }
        hotkey.add("control+k", () => openMainPalette());   # <-- closure ref
        return { openMainPalette, ... };                    # <-- facade
    }

Downstream addons extend such a service the only way a closure allows — by
patching ``start`` and mutating the object it returned::

    patch(commandService, {
        start(...args) {
            const svc = super.start(...args);
            Object.assign(svc, { openMainPalette() {} });    # neutralize it
            return svc;
        },
    });

That works for anyone who calls ``env.services.command.openMainPalette()``. It
does **not** work for the ``control+k`` registration above, which captured the
*function object* during ``super.start()``, before the patch ran. The patch
applies to some callers and silently skips others. No error is raised, and the
patch looks like it worked.

This is not hypothetical. ``enterprise/knowledge``'s portal webclient patches
``commandService`` to neutralize the command palette for portal users, who "can
not have access to some of its features (searching users, menus, ...)". The
direct calls are blocked; **Ctrl+K still opens the palette**, because
``command_service.js`` registered the hotkey against the closure identifier.
Reproduced in a real browser against the real service on 2026-08-03.

**Nothing else in this directory can see this**, and structurally so:

* ``js_public_surface`` and ``named_export_coherence`` reason about *module*
  exports. This is a call inside one function to another in the same scope —
  no export, no import, no edge.
* ``js_cycle_check``, ``js_layer_check`` and ``js_layer_cohesion`` reason about
  the import graph, which this does not touch.
* ``js_function_length`` measures how long ``start`` is, not who it calls.
* ESLint has no rule for it: calling a sibling closure is ordinary, correct
  JavaScript everywhere except inside a patchable service facade.

The property none of them holds is that a service's *own* callers see the same
implementation its consumers do.

Contract, over ``addons/web/static/src``:

    For any service registered in ``registry.category("services")``, no name
    published on the object ``start()`` returns may also be invoked as a bare
    identifier inside ``start()``.

The fix is mechanical and preserves the closure shape — name the facade and
route internal callers through it, so the lookup happens at call time::

    const commandServiceApi = { openMainPalette, ... };
    hotkey.add("control+k", () => commandServiceApi.openMainPalette());
    return commandServiceApi;

Parsed with acorn rather than a regex. An earlier hand-rolled scan of this same
property mis-classified ``tree_processor_service`` because ``return new Map(...)``
matched a "returns an instance" pattern; function and object extents are a
parsing problem.

Usage::

    python tooling/architecture/js_patch_blind_facade.py           # report
    python tooling/architecture/js_patch_blind_facade.py --check   # CI, exit 1
    python tooling/architecture/js_patch_blind_facade.py --json
    python tooling/architecture/js_patch_blind_facade.py --count
"""

import argparse
import json
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
WEB_SRC = ROOT / "addons" / "web" / "static" / "src"
ACORN = ROOT / "node_modules" / "acorn" / "dist" / "acorn.mjs"

SERVICE_MARKER = 'category("services").add'

# The analyzer runs in node because function and object extents are a parsing
# problem. Kept here rather than as a sibling .mjs so the gate is one file and
# cannot drift from its helper.
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
    """Every published name a service also calls through its closure.

    Raises ``RuntimeError`` rather than returning ``[]`` when the tree holds no
    services or the parser cannot run: a gate that reports "0 violations"
    because it analysed nothing is worse than no gate.

    ``src``/``acorn`` resolve at call time, not as default arguments. Binding
    them in the signature captures the module-level values at import and makes
    the roots unredirectable — the exact under-reach
    ``test_every_gate_refuses_an_empty_tree`` documents, which would leave this
    gate scanning the real tree while a probe believed it had emptied it.
    """
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
