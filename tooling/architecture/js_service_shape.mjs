/**
 * Shape analysis for `web`'s service factories, for `js_service_shape.py`.
 *
 * Answers one question per service module: does `start()` hand back an
 * INSTANCE (something carrying a prototype, so `patch(TheClass.prototype, …)`
 * reaches one method) or an object LITERAL (so the only seam is replacing
 * `start()` whole)?
 *
 * Parsed with espree rather than matched with a regex, for the reason
 * `js_function_length`'s docstring already records for function extents: the
 * shapes here nest, and brace counting gets them wrong. espree is already in
 * `node_modules` because ESLint parses every one of these files with it.
 *
 * Emits one JSON object per line: {file, service, shape, indirect}.
 * `shape` is "instance" | "literal" | "unknown". "unknown" is reported and NOT
 * counted, matching how `js_private_access` treats members no module declares:
 * a case the analysis cannot decide is not evidence of a defect.
 */
import { readFileSync } from "node:fs";
import * as espree from "espree";

const PARSE = { ecmaVersion: "latest", sourceType: "module", loc: true };

/**
 * Calls that return their own argument's shape. `reactive` wraps an object in a
 * Proxy and `markRaw` returns it untouched; neither adds a prototype, so what
 * comes out is exactly as (un)patchable as what went in.
 */
const TRANSPARENT_WRAPPERS = new Set(["reactive", "markRaw"]);

/** Walk every node, calling `fn` on each. */
function walk(node, fn) {
    if (!node || typeof node.type !== "string") {
        return;
    }
    fn(node);
    for (const key of Object.keys(node)) {
        if (key === "loc" || key === "range" || key === "parent") {
            continue;
        }
        const child = node[key];
        if (Array.isArray(child)) {
            child.forEach((c) => walk(c, fn));
        } else if (child && typeof child.type === "string") {
            walk(child, fn);
        }
    }
}

/** Return statements belonging to `fn` itself, not to functions nested in it. */
function ownReturns(fn) {
    const out = [];
    const isFn = (n) =>
        n.type === "FunctionExpression" ||
        n.type === "FunctionDeclaration" ||
        n.type === "ArrowFunctionExpression";
    (function visit(node, depth) {
        if (!node || typeof node.type !== "string") {
            return;
        }
        if (node !== fn && isFn(node)) {
            return; // a nested function's returns are its own
        }
        if (node.type === "ReturnStatement" && depth > 0) {
            out.push(node.argument);
        }
        for (const key of Object.keys(node)) {
            if (key === "loc" || key === "range") {
                continue;
            }
            const child = node[key];
            if (Array.isArray(child)) {
                child.forEach((c) => visit(c, depth + 1));
            } else if (child && typeof child.type === "string") {
                visit(child, depth + 1);
            }
        }
    })(fn, 0);
    return out;
}

/** Module-level `function name() {}` and `const name = () => {}`. */
function moduleFunctions(ast) {
    const fns = new Map();
    for (const node of ast.body) {
        const d = node.type === "ExportNamedDeclaration" ? node.declaration : node;
        if (!d) {
            continue;
        }
        if (d.type === "FunctionDeclaration" && d.id) {
            fns.set(d.id.name, d);
        } else if (d.type === "VariableDeclaration") {
            for (const decl of d.declarations) {
                if (
                    decl.id.type === "Identifier" &&
                    decl.init &&
                    (decl.init.type === "ArrowFunctionExpression" ||
                        decl.init.type === "FunctionExpression")
                ) {
                    fns.set(decl.id.name, decl.init);
                }
            }
        }
    }
    return fns;
}

/**
 * Classify what an expression evaluates to.
 * `depth` bounds indirection so a cycle cannot spin.
 */
function classify(expr, scope, modFns, depth = 0) {
    if (!expr || depth > 2) {
        return "unknown";
    }
    switch (expr.type) {
        case "NewExpression":
            return "instance";
        case "ObjectExpression":
            return "literal";
        case "Identifier": {
            const bound = scope.get(expr.name);
            return bound ? classify(bound, scope, modFns, depth + 1) : "unknown";
        }
        case "CallExpression": {
            // `reactive({...})` and `markRaw({...})` are shape-transparent: both
            // hand back the same object (a Proxy over it, for `reactive`), which
            // carries no prototype of its own. A service returning one is a
            // LITERAL for this gate's purpose, and reporting it "unknown" hid
            // three of them — `ui`, `pwa` and `web.frequent.emoji`.
            if (
                expr.callee.type === "Identifier" &&
                TRANSPARENT_WRAPPERS.has(expr.callee.name) &&
                expr.arguments.length
            ) {
                return classify(expr.arguments[0], scope, modFns, depth + 1);
            }
            // `return makeActionManager(env)` — follow one hop into a local factory.
            if (expr.callee.type === "Identifier" && modFns.has(expr.callee.name)) {
                const fn = modFns.get(expr.callee.name);
                const rets = ownReturns(fn).filter(Boolean);
                const inner = localScope(fn);
                const kinds = new Set(
                    rets.map((r) => classify(r, inner, modFns, depth + 1)),
                );
                if (kinds.size === 1) {
                    return [...kinds][0];
                }
            }
            return "unknown";
        }
        case "AwaitExpression":
            return classify(expr.argument, scope, modFns, depth + 1);
        default:
            return "unknown";
    }
}

/** `const x = <expr>` bindings declared directly inside `fn`. */
function localScope(fn) {
    const scope = new Map();
    walk(fn.body, (n) => {
        if (n.type === "VariableDeclarator" && n.id.type === "Identifier" && n.init) {
            if (!scope.has(n.id.name)) {
                scope.set(n.id.name, n.init);
            }
        }
    });
    return scope;
}

for (const file of process.argv.slice(2)) {
    let ast;
    try {
        ast = espree.parse(readFileSync(file, "utf8"), PARSE);
    } catch {
        continue; // a file ESLint would reject anyway; not this gate's report to make
    }
    const modFns = moduleFunctions(ast);

    // `const services = registry.category("services")` — the bound form. Without
    // this the scan misses every service registered through it, which is how
    // `overlay`, `pwa` and `color_scheme` sat outside the budget unnoticed. Same
    // defect `js_registry_layering` had for a category exported as a symbol.
    const servicesBindings = new Set();
    walk(ast, (n) => {
        if (
            n.type === "VariableDeclarator" &&
            n.id.type === "Identifier" &&
            n.init?.type === "CallExpression" &&
            n.init.callee.type === "MemberExpression" &&
            n.init.callee.property.name === "category" &&
            n.init.arguments[0]?.value === "services"
        ) {
            servicesBindings.add(n.id.name);
        }
    });

    const isServicesAdd = (callee) => {
        if (callee.type !== "MemberExpression" || callee.property.name !== "add") {
            return false;
        }
        const target = callee.object;
        if (target.type === "Identifier") {
            return servicesBindings.has(target.name);
        }
        return (
            target.type === "CallExpression" &&
            target.callee.type === "MemberExpression" &&
            target.callee.property.name === "category" &&
            target.arguments[0]?.value === "services"
        );
    };

    // Which identifiers are registered as services, and under what name.
    const registered = new Map();
    walk(ast, (n) => {
        if (
            n.type === "CallExpression" &&
            isServicesAdd(n.callee) &&
            n.arguments[1]?.type === "Identifier"
        ) {
            registered.set(n.arguments[1].name, n.arguments[0]?.value ?? "?");
        }
    });
    if (!registered.size) {
        continue;
    }

    // Their object literals, and the `start` each declares.
    const objects = new Map();
    walk(ast, (n) => {
        if (
            n.type === "VariableDeclarator" &&
            n.id.type === "Identifier" &&
            n.init?.type === "ObjectExpression" &&
            registered.has(n.id.name)
        ) {
            objects.set(n.id.name, n.init);
        }
    });

    for (const [ident, service] of registered) {
        const obj = objects.get(ident);
        if (!obj) {
            continue;
        }
        const startProp = obj.properties.find(
            (p) => p.type === "Property" && p.key?.name === "start",
        );
        if (!startProp || !startProp.value?.body) {
            continue;
        }
        const fn = startProp.value;
        const rets = ownReturns(fn).filter(Boolean);
        const scope = localScope(fn);
        const kinds = new Set(rets.map((r) => classify(r, scope, modFns)));
        let shape = "unknown";
        if (kinds.size === 1) {
            shape = [...kinds][0];
        } else if (kinds.size > 1 && !kinds.has("unknown")) {
            // A start() returning both shapes is a literal for our purposes: at
            // least one path hands back something without a prototype.
            shape = kinds.has("literal") ? "literal" : "instance";
        }
        process.stdout.write(
            JSON.stringify({
                file,
                service,
                shape,
                lines: fn.body.loc.end.line - fn.body.loc.start.line + 1,
            }) + "\n",
        );
    }
}
