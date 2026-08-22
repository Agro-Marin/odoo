// Resolve what every OWL template calls against what its component provides.
//
// Both halves are parsed, not matched. That is the whole point: a regex form of
// this check reports CSS `url(` inside a `t-att-style` string as a method call,
// misses the members a class gets from a mixin, and confuses two classes that
// share a name in different files. Parsing the QWeb expressions with the same
// parser that reads the JS removes the first outright and makes the other two
// tractable.
//
// stdin: JSON { js: [paths], xml: [paths] }
// stdout: JSON { templates, classes, findings: [...], skipped: {...} }

import { readFileSync } from "node:fs";
import * as espree from "espree";

const PARSE = { ecmaVersion: "latest", sourceType: "module", loc: true };

// Ways this tree installs a member bag onto a prototype. `Object.assign` is the
// common one; `Object.defineProperties` is how `installListRendererMixin` does
// it, in order to make the members non-enumerable and to refuse a collision.
const OBJECT_INSTALLERS = new Set(["assign", "defineProperties"]);
const EXPR_PARSE = { ecmaVersion: "latest", loc: false };

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

function keyName(node) {
    const key = node.key ?? node;
    if (!key) {
        return null;
    }
    return key.type === "Identifier"
        ? key.name
        : key.type === "Literal"
          ? String(key.value)
          : null;
}

/** Members a class body declares itself, plus anything `this.x =` in it. */
function ownMembers(classNode) {
    const names = new Set();
    for (const el of classNode.body.body) {
        const name = keyName(el);
        if (name) {
            names.add(name);
        }
    }
    walk(classNode, (node) => {
        if (
            node.type === "AssignmentExpression" &&
            node.left.type === "MemberExpression" &&
            node.left.object.type === "ThisExpression" &&
            node.left.property.type === "Identifier"
        ) {
            names.add(node.left.property.name);
        }
    });
    return names;
}

function staticTemplate(classNode) {
    for (const el of classNode.body.body) {
        if (
            el.type === "PropertyDefinition" &&
            el.static &&
            keyName(el) === "template" &&
            el.value?.type === "Literal" &&
            typeof el.value.value === "string"
        ) {
            return el.value.value;
        }
    }
    return null;
}

function superName(classNode) {
    const sup = classNode.superClass;
    if (!sup) {
        return null;
    }
    if (sup.type === "Identifier") {
        return sup.name;
    }
    // `class X extends Y.Z` — take the head; good enough to reach a local name.
    if (sup.type === "MemberExpression" && sup.object.type === "Identifier") {
        return sup.object.name;
    }
    return null;
}

/**
 * A module's JS facts. Classes are keyed by (file, name) so that two classes
 * sharing a name in different files cannot be confused — the failure that made
 * the regex prototype report `Many2One.openRecord` as missing when it exists.
 */
function readModule(path) {
    let ast;
    try {
        ast = espree.parse(readFileSync(path, "utf-8"), PARSE);
    } catch (error) {
        return { path, parseError: String(error.message || error) };
    }
    const classes = [];
    const objects = new Map(); // local const name -> member names (mixin literals)
    const imports = new Map(); // local name -> source specifier
    const mixinsInto = new Map(); // class local name -> [mixin local names]

    for (const node of ast.body) {
        if (node.type === "ImportDeclaration") {
            for (const spec of node.specifiers) {
                imports.set(spec.local.name, node.source.value);
            }
        }
    }

    walk(ast, (node) => {
        if (node.type === "ClassDeclaration" || node.type === "ClassExpression") {
            classes.push({
                name: node.id?.name || null,
                line: node.loc.start.line,
                members: [...ownMembers(node)],
                super: superName(node),
                template: staticTemplate(node),
            });
            return;
        }
        if (
            node.type === "VariableDeclarator" &&
            node.id.type === "Identifier" &&
            node.init?.type === "ObjectExpression"
        ) {
            objects.set(
                node.id.name,
                node.init.properties.map(keyName).filter(Boolean),
            );
            return;
        }
        if (node.type !== "CallExpression") {
            return;
        }
        // `patch(X.prototype, {...})` and `patch(X, {...})`
        if (node.callee.type === "Identifier" && node.callee.name === "patch") {
            const [target, ext] = node.arguments;
            const owner =
                target?.type === "MemberExpression"
                    ? target.object.type === "Identifier"
                        ? target.object.name
                        : null
                    : target?.type === "Identifier"
                      ? target.name
                      : null;
            if (owner && ext?.type === "ObjectExpression") {
                const names = ext.properties.map(keyName).filter(Boolean);
                mixinsInto.set(owner, [
                    ...(mixinsInto.get(owner) || []),
                    { inline: names },
                ]);
            }
            return;
        }
        // `Object.assign(X.prototype, mixin)` and any single-call installer whose
        // arguments are (mixinIdent, ...) applied to a known class — the shape
        // `installListRendererMixin(listStylingMixin, "…")` uses.
        const args = node.arguments || [];
        if (
            node.callee.type === "MemberExpression" &&
            node.callee.object.type === "Identifier" &&
            node.callee.object.name === "Object" &&
            OBJECT_INSTALLERS.has(node.callee.property.name) &&
            args[0]?.type === "MemberExpression" &&
            args[0].object.type === "Identifier"
        ) {
            const owner = args[0].object.name;
            for (const a of args.slice(1)) {
                if (a.type === "Identifier") {
                    mixinsInto.set(owner, [
                        ...(mixinsInto.get(owner) || []),
                        { ref: a.name },
                    ]);
                } else if (a.type === "ObjectExpression") {
                    mixinsInto.set(owner, [
                        ...(mixinsInto.get(owner) || []),
                        { inline: a.properties.map(keyName).filter(Boolean) },
                    ]);
                }
            }
        }
    });

    // A bespoke installer: any top-level function that Object.assign's a
    // parameter onto a fixed class prototype. Record the class it installs onto
    // and treat every call of it as installing its first argument.
    const installers = new Map(); // fn name -> class name
    walk(ast, (node) => {
        if (node.type !== "FunctionDeclaration" || !node.id || !node.params.length) {
            return;
        }
        // Any parameterised function that installs onto some `X.prototype`
        // counts, without insisting the parameter reaches the install call
        // textually. `installListRendererMixin` derives its descriptors two
        // statements earlier (`getOwnPropertyDescriptors(mixin)`), so a
        // parameter match found nothing and all four members it installs were
        // reported missing.
        //
        // The looseness is safe in ONE direction and that is the direction this
        // gate runs in: over-recognising an installer can only ADD names to a
        // component's membership, and a gate that reports a MISSING name turns
        // an over-approximation into a false negative, never a false positive.
        // Every resolution step here is written to err that way on purpose.
        walk(node.body, (inner) => {
            if (
                inner.type === "CallExpression" &&
                inner.callee.type === "MemberExpression" &&
                inner.callee.object.name === "Object" &&
                OBJECT_INSTALLERS.has(inner.callee.property.name) &&
                inner.arguments[0]?.type === "MemberExpression" &&
                inner.arguments[0].object.type === "Identifier"
            ) {
                installers.set(node.id.name, inner.arguments[0].object.name);
            }
        });
    });
    walk(ast, (node) => {
        if (
            node.type === "CallExpression" &&
            node.callee.type === "Identifier" &&
            installers.has(node.callee.name) &&
            node.arguments[0]?.type === "Identifier"
        ) {
            const owner = installers.get(node.callee.name);
            mixinsInto.set(owner, [
                ...(mixinsInto.get(owner) || []),
                { ref: node.arguments[0].name },
            ]);
        }
    });

    return {
        path,
        classes,
        objects: [...objects],
        imports: [...imports],
        mixinsInto: [...mixinsInto],
    };
}

// ---------------------------------------------------------------- QWeb side

// Attributes whose value is an EXPRESSION.
const EXPR_ATTR =
    /^t-(?:on-[\w.-]+|att-[\w:.-]+|att|if|elif|out|esc|value|foreach|key|props|component|slot-scope|model(?:\.\w+)*)$/;
// Attributes whose value is a STRING with {{…}} / #{…} holes.
const INTERP_ATTR = /^t-attf-[\w:.-]+$/;
const INTERP = /\{\{([\s\S]*?)\}\}|#\{([\s\S]*?)\}/g;

// Attributes are scanned directly, NOT tag by tag. A tag-level regex has to
// bound itself on `>`, and `t-on-click="() => this.foo()"` contains one inside
// the value -- so every arrow-function handler, which is the commonest place a
// template calls a component method, fell outside the match. That is not a
// tidiness point: it made the first draft of this gate blind to the exact
// defect it was written for, and it reported a clean tree while doing so. A
// quoted value cannot contain a bare `"`, so the value delimiter is sound where
// the tag delimiter is not.
const ATTR = /([\w:.@-]+)\s*=\s*"([^"]*)"/g;

function decode(text) {
    return text
        .replace(/&lt;/g, "<")
        .replace(/&gt;/g, ">")
        .replace(/&amp;/g, "&")
        .replace(/&quot;/g, '"')
        .replace(/&apos;/g, "'")
        .replace(/&#39;/g, "'");
}

/** Names an expression calls: `this.foo(...)` and bare `foo(...)`. */
/** QWeb accepts Python's boolean operators. espree does not. */
function toJs(expr) {
    return expr
        .replace(/(^|[\s(,[])not(?=[\s(])/g, "$1!")
        .replace(/(^|[\s)\]])and(?=[\s(])/g, "$1&&")
        .replace(/(^|[\s)\]])or(?=[\s(])/g, "$1||");
}

function calledIn(rawExpr, out, unparsable) {
    const expr = toJs(rawExpr);
    let ast;
    try {
        ast = espree.parse(`(${expr})`, EXPR_PARSE);
    } catch {
        try {
            ast = espree.parse(expr, EXPR_PARSE);
        } catch {
            unparsable.push(expr);
            return;
        }
    }
    walk(ast, (node) => {
        if (node.type !== "CallExpression") {
            return;
        }
        // `foo?.()` and `this.foo?.()` are the author saying the name may not be
        // there. `website.DynamicSnippetOption` does exactly that with
        // `!!showCoverImage?.()`, and reporting it would be telling a template
        // off for the guard it was right to write.
        if (node.optional || node.callee.optional) {
            return;
        }
        const callee = node.callee;
        if (
            callee.type === "MemberExpression" &&
            callee.object.type === "ThisExpression" &&
            callee.property.type === "Identifier"
        ) {
            out.add(callee.property.name);
        } else if (callee.type === "Identifier") {
            out.add(callee.name);
        }
    });
}

function templatesIn(path) {
    const text = readFileSync(path, "utf-8");
    const blocks = [];
    const re = /<t\s+([^>]*?)t-name="([^"]+)"([^>]*)>/g;
    let m;
    const marks = [];
    while ((m = re.exec(text))) {
        marks.push({ name: m[2], start: m.index, head: m[0] });
    }
    for (let i = 0; i < marks.length; i++) {
        const end = i + 1 < marks.length ? marks[i + 1].start : text.length;
        blocks.push({
            name: marks[i].name,
            body: text.slice(marks[i].start, end),
            head: marks[i].head,
            line: text.slice(0, marks[i].start).split("\n").length,
        });
    }
    return blocks;
}

function analyseTemplate(block) {
    const called = new Set();
    const bound = new Set();
    const unparsable = [];
    ATTR.lastIndex = 0;
    let a;
    while ((a = ATTR.exec(block.body))) {
        const [, name, rawValue] = a;
        const value = decode(rawValue);
        if (name === "t-set" || name === "t-as" || name === "t-slot-scope") {
            bound.add(value);
            continue;
        }
        if (EXPR_ATTR.test(name)) {
            calledIn(value, called, unparsable);
        } else if (INTERP_ATTR.test(name)) {
            INTERP.lastIndex = 0;
            let hole;
            while ((hole = INTERP.exec(value))) {
                calledIn(hole[1] ?? hole[2], called, unparsable);
            }
        }
    }
    return { called: [...called], bound: [...bound], unparsable };
}

// ---------------------------------------------------------------- driver

const input = JSON.parse(readFileSync(0, "utf-8"));
const modules = input.js.map(readModule);
const templates = [];
for (const path of input.xml) {
    for (const block of templatesIn(path)) {
        templates.push({ path, ...block, ...analyseTemplate(block) });
    }
}
process.stdout.write(
    JSON.stringify({
        modules,
        templates: templates.map((t) => ({
            path: t.path,
            name: t.name,
            line: t.line,
            called: t.called,
            bound: t.bound,
            inherits: /t-inherit=/.test(t.head),
            unparsable: t.unparsable.length,
        })),
    }),
);
