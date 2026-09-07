import { readFileSync } from "node:fs";
import * as espree from "espree";

const PARSE = { ecmaVersion: "latest", sourceType: "module", loc: true };

const FN = new Set([
    "FunctionExpression",
    "ArrowFunctionExpression",
    "FunctionDeclaration",
]);

// A callback the test body itself drives: its assertions run in the test's own
// straight-line flow, so non-invocation is not a risk.
const DRIVEN_BY_CALLER = new Set([
    "map",
    "forEach",
    "filter",
    "find",
    "findIndex",
    "some",
    "every",
    "flatMap",
    "reduce",
    "sort",
    "then",
    "catch",
    "finally",
    "toThrow",
    "expect",
]);

function walk(node, fn, parent = null) {
    if (!node || typeof node.type !== "string") return;
    fn(node, parent);
    for (const key of Object.keys(node)) {
        if (key === "loc" || key === "range" || key === "parent") continue;
        const child = node[key];
        if (Array.isArray(child)) {
            for (const c of child)
                if (c && typeof c.type === "string") walk(c, fn, node);
        } else if (child && typeof child.type === "string") walk(child, fn, node);
    }
}

const within = (inner, outer) =>
    inner.range[0] >= outer.range[0] && inner.range[1] <= outer.range[1];

function isTestRegistration(node) {
    if (node.type !== "CallExpression") return false;
    const c = node.callee;
    if (c.type === "Identifier") return c.name === "test";
    return (
        c.type === "MemberExpression" &&
        c.object?.type === "Identifier" &&
        c.object.name === "test" &&
        ["tags", "only", "debug", "skip", "todo"].includes(c.property?.name)
    );
}

/** Every identifier the function assigns to or updates — a sentinel candidate. */
function assignedNames(fn) {
    const names = new Set();
    walk(fn, (n) => {
        if (n.type === "AssignmentExpression" && n.left.type === "Identifier")
            names.add(n.left.name);
        if (n.type === "UpdateExpression" && n.argument.type === "Identifier")
            names.add(n.argument.name);
    });
    return names;
}

for (const file of process.argv.slice(2)) {
    const text = readFileSync(file, "utf8");
    let ast;
    try {
        ast = espree.parse(text, { ...PARSE, range: true });
    } catch (error) {
        process.stderr.write(`${file}: ${error.message}\n`);
        process.exitCode = 1;
        continue;
    }
    walk(ast, (node) => {
        if (!isTestRegistration(node)) return;
        const body = node.arguments.find((a) => a && FN.has(a.type));
        if (!body) return;
        const bodyText = text.slice(body.range[0], body.range[1]);
        // The test pins how many assertions must run, or uses the step protocol.
        if (/expect\.assertions\s*\(|verifySteps\s*\(/.test(bodyText)) return;

        // Deferred functions: declared inside the test, not driven by it.
        const deferred = [];
        walk(body, (n, parent) => {
            if (n === body) return;
            const isFn = FN.has(n.type);
            const isMethod = n.type === "MethodDefinition" && n.kind !== "constructor";
            if (!isFn && !isMethod) return;
            if (
                isFn &&
                parent?.type === "CallExpression" &&
                parent.arguments.includes(n)
            ) {
                const callee = parent.callee;
                const name =
                    callee.type === "MemberExpression"
                        ? callee.property?.name
                        : callee.name;
                if (DRIVEN_BY_CALLER.has(name)) return;
            }
            if (isFn && parent?.type === "MethodDefinition") return; // counted as the method
            deferred.push(
                isMethod ? Object.assign(n.value, { _method: n.key?.name }) : n,
            );
        });
        if (!deferred.length) return;

        // Hoot already fails a test that runs no assertion at all, so a test
        // whose ONLY assertions sit in a dead handler is caught today. What is
        // not caught is a dead handler MASKED by an assertion in the test's own
        // flow: one assertion runs, the test is green, and the assertion that
        // names the behaviour never executed. That masking is the defect.
        let masked = false;
        walk(body, (n) => {
            if (masked) return;
            if (n.type !== "CallExpression" || n.callee.type !== "Identifier") return;
            if (n.callee.name !== "expect") return;
            if (deferred.some((d) => within(n, d))) return;
            masked = true;
        });
        if (!masked) return;

        for (const fn of deferred) {
            let asserts = false;
            walk(fn, (n) => {
                if (
                    n.type === "CallExpression" &&
                    n.callee.type === "Identifier" &&
                    n.callee.name === "expect"
                ) {
                    // ignore an expect() nested in a deeper deferred function
                    const deeper = deferred.some(
                        (d) => d !== fn && within(d, fn) && within(n, d),
                    );
                    if (!deeper) asserts = true;
                }
            });
            if (!asserts) continue;

            // A sentinel this function sets, asserted outside it, proves it ran.
            const sentinels = assignedNames(fn);
            // So does the result of the call it was handed to: a callback whose
            // caller returns its value cannot have been skipped if that value
            // is asserted. `const seen = withX(() => {...}); expect(seen)...`
            let host = null;
            walk(body, (n) => {
                if (n.type === "CallExpression" && n.arguments.includes(fn)) host = n;
            });
            if (host) {
                walk(body, (n) => {
                    if (
                        n.type === "VariableDeclarator" &&
                        n.init === host &&
                        n.id.type === "Identifier"
                    ) {
                        sentinels.add(n.id.name);
                    }
                });
            }
            let proven = false;
            walk(body, (n) => {
                if (proven) return;
                if (n.type !== "CallExpression" || n.callee.type !== "Identifier")
                    return;
                if (n.callee.name !== "expect") return;
                if (within(n, fn)) return;
                const t = text.slice(n.range[0], n.range[1]);
                for (const s of sentinels)
                    if (new RegExp(`\\b${s}\\b`).test(t)) proven = true;
            });
            if (proven) continue;

            const nameArg = node.arguments.find(
                (a) => a && (a.type === "Literal" || a.type === "TemplateLiteral"),
            );
            process.stdout.write(
                JSON.stringify({
                    file,
                    line: fn.loc.start.line,
                    method: fn._method ?? null,
                    test: nameArg
                        ? text
                              .slice(nameArg.range[0] + 1, nameArg.range[1] - 1)
                              .slice(0, 90)
                        : "(unnamed)",
                }) + "\n",
            );
        }
    });
}
