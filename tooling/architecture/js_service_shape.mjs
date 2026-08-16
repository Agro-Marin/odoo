import { readFileSync } from "node:fs";
import * as espree from "espree";

const PARSE = { ecmaVersion: "latest", sourceType: "module", loc: true };

const TRANSPARENT_WRAPPERS = new Set(["reactive", "markRaw"]);

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
            return;
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
            if (
                expr.callee.type === "Identifier" &&
                TRANSPARENT_WRAPPERS.has(expr.callee.name) &&
                expr.arguments.length
            ) {
                return classify(expr.arguments[0], scope, modFns, depth + 1);
            }
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
        continue;
    }
    const modFns = moduleFunctions(ast);

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
