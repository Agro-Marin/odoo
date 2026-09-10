// Body-aware half of js_naming_vocabulary.py, run by its --bodies flag.
// Reads every .js under the roots given as arguments with the acorn eslint
// already ships in node_modules, and prints one JSON row per definition whose
// leading verb promises what the body does not deliver: a get/is/has/can that
// returns nothing, or a set/update/add/remove/reset that returns a value. The
// regex reader cannot ask either question, and `getResults` -- a get that
// pushed into this.commands and returned nothing -- got past it.
"use strict";
const fs = require("fs");
const path = require("path");
const acorn = require("acorn");

const SKIP_DIRS = new Set(["lib", "libs", "node_modules", "vendored", "_vendor"]);
const PRODUCERS = new Set(["get", "is", "has", "can", "find"]);
const MUTATORS = new Set(["set", "update", "add", "remove", "reset", "clear"]);

function files(dir, out = []) {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) {
            if (!SKIP_DIRS.has(entry.name)) {
                files(full, out);
            }
        } else if (full.endsWith(".js")) {
            out.push(full);
        }
    }
    return out;
}

function walk(node, visit, stopAt) {
    if (!node || typeof node.type !== "string") {
        return;
    }
    visit(node);
    if (stopAt.has(node.type)) {
        return;
    }
    for (const key of Object.keys(node)) {
        if (key === "loc") {
            continue;
        }
        const value = node[key];
        if (Array.isArray(value)) {
            for (const item of value) {
                walk(item, visit, stopAt);
            }
        } else if (value && typeof value.type === "string") {
            walk(value, visit, stopAt);
        }
    }
}

const FUNCTION_TYPES = new Set([
    "FunctionExpression",
    "FunctionDeclaration",
    "ArrowFunctionExpression",
]);

function returnShape(fn) {
    if (fn.body && fn.body.type !== "BlockStatement") {
        return { value: true, statements: 1 };
    }
    let value = false;
    walk(
        fn.body,
        (n) => {
            if (n.type === "ReturnStatement" && n.argument) {
                value = true;
            }
        },
        FUNCTION_TYPES,
    );
    return { value, statements: fn.body ? fn.body.body.length : 0 };
}

function leadingVerb(name) {
    const stem = name.replace(/^[_$]+/, "");
    const head = stem.match(/^[a-z]+/);
    if (!head || head[0].length === stem.length) {
        return null;
    }
    return head[0];
}

function classify(name, fn, kind) {
    const verb = leadingVerb(name);
    if (!verb || kind === "get" || kind === "set" || fn.async || fn.generator) {
        return null;
    }
    // A store record's `<field>OnUpdate` hook and an empty extension-point
    // stub (`_isActive(action) {}`) are contracts, not producers.
    if (name.endsWith("OnUpdate")) {
        return null;
    }
    const shape = returnShape(fn);
    if (shape.statements === 0) {
        return null;
    }
    if (PRODUCERS.has(verb) && !shape.value) {
        return `a \`${verb}\` that returns nothing`;
    }
    if (
        MUTATORS.has(verb) &&
        shape.value &&
        fn.body &&
        fn.body.type === "BlockStatement"
    ) {
        // Returning the receiver or the argument back (`return formData;`) is
        // the fluent idiom; a literal is an early-exit guard (`return false;`);
        // a call is delegation (`return this._mutex.exec(...)`); a function is
        // the subscribe idiom handing back its disposer. None is a produced value.
        const params = new Set(
            fn.params
                .map((p) => (p.type === "AssignmentPattern" ? p.left : p))
                .filter((p) => p.type === "Identifier")
                .map((p) => p.name),
        );
        // `const res = super.addEmoji(str); ...; return res;` forwards a
        // delegated result the same way `return super.addEmoji(str)` would.
        walk(
            fn.body,
            (n) => {
                if (
                    n.type === "VariableDeclarator" &&
                    n.id.type === "Identifier" &&
                    n.init &&
                    (n.init.type === "CallExpression" ||
                        n.init.type === "AwaitExpression")
                ) {
                    params.add(n.id.name);
                }
            },
            FUNCTION_TYPES,
        );
        let produced = false;
        walk(
            fn.body,
            (n) => {
                if (n.type !== "ReturnStatement" || !n.argument) {
                    return;
                }
                const a = n.argument;
                if (
                    a.type === "ThisExpression" ||
                    (a.type === "Identifier" && params.has(a.name)) ||
                    a.type === "Literal" ||
                    a.type === "CallExpression" ||
                    a.type === "AwaitExpression" ||
                    FUNCTION_TYPES.has(a.type)
                ) {
                    return;
                }
                produced = true;
            },
            FUNCTION_TYPES,
        );
        if (!produced) {
            return null;
        }
        return `a \`${verb}\` that returns a value`;
    }
    return null;
}

const rows = [];
for (const root of process.argv.slice(2)) {
    for (const file of files(root)) {
        let ast;
        try {
            ast = acorn.parse(fs.readFileSync(file, "utf8"), {
                ecmaVersion: "latest",
                sourceType: "module",
                locations: true,
            });
        } catch {
            continue;
        }
        const seen = (name, fn, kind, line) => {
            const why = classify(name, fn, kind);
            if (why) {
                rows.push({ path: file, line, name, verb: leadingVerb(name), why });
            }
        };
        walk(
            ast,
            (n) => {
                if (n.type === "MethodDefinition" && n.key.type === "Identifier") {
                    seen(n.key.name, n.value, n.kind, n.loc.start.line);
                } else if (
                    (n.type === "Property" || n.type === "PropertyDefinition") &&
                    n.key.type === "Identifier" &&
                    n.value &&
                    FUNCTION_TYPES.has(n.value.type)
                ) {
                    seen(n.key.name, n.value, n.kind || "init", n.loc.start.line);
                } else if (n.type === "FunctionDeclaration" && n.id) {
                    seen(n.id.name, n, "init", n.loc.start.line);
                }
            },
            new Set(),
        );
    }
}
process.stdout.write(JSON.stringify(rows));
