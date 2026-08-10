/**
 * Defines/uses extraction for JS mixin compositions, for `js_mixin_coupling.py`.
 *
 * The Python half explains why this exists. In short: a mixin is a fragment of
 * a class, its collaborators are reached through `this`, and `this.x` produces
 * no import edge — so `js_layer_check` and `js_private_access` both see nothing.
 * `mixin_coupling_check.py` already makes exactly this argument for Python's
 * `BaseModel` and its 23 `__slots__ = ()` mixins. This is the JS counterpart.
 *
 * Per unit (one mixin module, or the composing base) it emits:
 *
 *   defines  — names bound in the body of a participating class
 *   uses     — every `this.X` read or written inside such a class
 *
 * A "participating class" is the body of a mixin factory
 * (`export const FooMixin = (Base) => class extends Base { … }`) or a class
 * declared in a module that composes one. Restricting to those bodies matters
 * for the same reason `mixin_coupling_check.py` restricts to
 * `_ModelStubs`/`*Mixin` subclasses: a module-local helper class that happens to
 * define `get length()` would otherwise contribute phantom edges.
 *
 * Parsed with espree rather than matched with a regex, following
 * `js_service_shape.mjs`: mixin bodies nest arrow functions, object literals and
 * further classes, and `this` inside a nested *arrow* still belongs to the
 * enclosing method while `this` inside a nested `function` does not. Brace
 * counting cannot tell those apart; a parser can.
 *
 * Emits one JSON object per line: {file, classes, defines, uses, dynamic}.
 * `dynamic` counts `this[expr]` accesses — reported, never counted, matching how
 * `js_private_access` treats members no module declares: a case the analysis
 * cannot decide is not evidence of a defect.
 */
import { readFileSync } from "node:fs";
import * as espree from "espree";

const PARSE = { ecmaVersion: "latest", sourceType: "module", loc: true };

/** Walk every node, calling `fn(node)`. */
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

/** Every ClassBody in the file, with a best-effort name for reporting. */
function classBodies(ast) {
    const found = [];
    walk(ast, (node) => {
        if (node.type !== "ClassDeclaration" && node.type !== "ClassExpression") {
            return;
        }
        found.push({ name: node.id?.name || null, node });
    });
    return found;
}

/**
 * Object-literal mixins: `export const fooMixin = { … }`, merged onto a
 * prototype by `Object.assign`.
 *
 * The second composition shape in this tree, and invisible to `classBodies`:
 * `views/list/list_renderer.js` installs `listStylingMixin`,
 * `listGroupRenderingMixin` and `listSortingMixin` that way, and each is an
 * `ObjectExpression`, not a class. Running the analyzer over them before this
 * reported `classes: [], defines: [], uses: []` for all three — so enumerating
 * the composition in `COMPOSITIONS` would have bought a **vacuous pass**, the
 * failure `test_architecture_doc_is_not_vacuous.py` exists to prevent
 * elsewhere. The coupling it could not see: 62 `this.` references over 30
 * distinct members, including `this.render`, `this.state`, `this.actionService`
 * and `this._readonlyCache` — a private reached from another module, which
 * `js_private_access` cannot see either, for the same merge-into-the-prototype
 * reason.
 *
 * Matched by the `Mixin` name suffix rather than by shape. Every object literal
 * in a module is not a mixin, and the suffix is the convention both this tree's
 * composition sites use; a shape-based guess would sweep in option bags.
 */
function objectMixinBodies(ast) {
    const found = [];
    walk(ast, (node) => {
        if (node.type !== "VariableDeclarator") {
            return;
        }
        if (node.id?.type !== "Identifier" || !/Mixin$/.test(node.id.name)) {
            return;
        }
        if (node.init?.type !== "ObjectExpression") {
            return;
        }
        found.push({ name: node.id.name, node: node.init });
    });
    return found;
}

/** Names an object-literal mixin binds. Computed keys are skipped, as above. */
function definedNamesFromObject(objectNode) {
    const names = new Set();
    for (const prop of objectNode.properties) {
        if (prop.type !== "Property" || prop.computed || !prop.key) {
            continue;
        }
        const name = prop.key.name ?? prop.key.value;
        if (typeof name === "string") {
            names.add(name);
        }
    }
    return names;
}

/**
 * `this.X` inside an object-literal mixin's methods.
 *
 * Only `FunctionExpression` values are entered — a method shorthand, a
 * `foo: function () {}`, or a getter/setter. An **arrow** property is skipped
 * on purpose: its `this` is the enclosing module scope, not the prototype the
 * mixin is merged onto, so its reads say nothing about the composition.
 */
function usedNamesFromObject(objectNode) {
    const names = new Set();
    let dynamic = 0;
    for (const prop of objectNode.properties) {
        if (prop.type !== "Property" || prop.value?.type !== "FunctionExpression") {
            continue;
        }
        prop.value.__isMethodValue = true;
        const used = usedNames({ body: { body: [prop] } });
        delete prop.value.__isMethodValue;
        for (const name of used.names) {
            names.add(name);
        }
        dynamic += used.dynamic;
    }
    return { names, dynamic };
}

/**
 * Names a class body binds: methods, getters/setters, and fields.
 *
 * Computed keys (`[SYMBOL]() {}`) are skipped — the name is not statically
 * known, and inventing one would create an edge to a member nothing can be
 * shown to use.
 */
function definedNames(classNode) {
    const names = new Set();
    for (const member of classNode.body.body) {
        if (member.computed || !member.key) {
            continue;
        }
        const name = member.key.name ?? member.key.value;
        if (typeof name === "string") {
            names.add(name);
        }
    }
    return names;
}

/**
 * `this.X` names appearing anywhere inside a class body, excluding those inside
 * a nested non-arrow `function`, whose `this` is a different object.
 *
 * Nested classes rebind `this` too, and their own members are collected as their
 * own unit, so they are skipped here rather than folded into the parent.
 */
function usedNames(classNode) {
    const names = new Set();
    let dynamic = 0;
    const visit = (node, insideOwnThis) => {
        if (!node || typeof node.type !== "string") {
            return;
        }
        const reboundThis =
            node.type === "FunctionExpression" ||
            node.type === "FunctionDeclaration" ||
            node.type === "ClassDeclaration" ||
            node.type === "ClassExpression";
        // A method's own FunctionExpression is where its body lives; entering it
        // keeps `this` bound to the instance. Only a nested one rebinds.
        const own = node.__isMethodValue ? true : insideOwnThis && !reboundThis;
        if (
            node.type === "MemberExpression" &&
            node.object.type === "ThisExpression" &&
            own
        ) {
            if (node.computed) {
                dynamic += 1;
            } else if (node.property.type === "Identifier") {
                names.add(node.property.name);
            }
        }
        for (const key of Object.keys(node)) {
            if (key === "loc" || key === "range" || key === "parent") {
                continue;
            }
            const child = node[key];
            if (Array.isArray(child)) {
                child.forEach((c) => visit(c, own));
            } else if (child && typeof child.type === "string") {
                visit(child, own);
            }
        }
    };
    for (const member of classNode.body.body) {
        if (member.value) {
            // Mark the method's own function node so `visit` does not treat it
            // as a `this`-rebinding nested function.
            member.value.__isMethodValue = true;
        }
        visit(member, true);
        if (member.value) {
            delete member.value.__isMethodValue;
        }
    }
    return { names, dynamic };
}

for (const file of process.argv.slice(2)) {
    let ast;
    try {
        ast = espree.parse(readFileSync(file, "utf8"), PARSE);
    } catch (error) {
        process.stderr.write(`parse failed: ${file}: ${error.message}\n`);
        process.exitCode = 1;
        continue;
    }
    const defines = new Set();
    const uses = new Set();
    const names = [];
    let dynamic = 0;
    for (const { name, node } of classBodies(ast)) {
        names.push(name);
        for (const d of definedNames(node)) {
            defines.add(d);
        }
        const used = usedNames(node);
        for (const u of used.names) {
            uses.add(u);
        }
        dynamic += used.dynamic;
    }
    for (const { name, node } of objectMixinBodies(ast)) {
        names.push(name);
        for (const d of definedNamesFromObject(node)) {
            defines.add(d);
        }
        const used = usedNamesFromObject(node);
        for (const u of used.names) {
            uses.add(u);
        }
        dynamic += used.dynamic;
    }
    process.stdout.write(
        `${JSON.stringify({
            file,
            classes: names,
            defines: [...defines].sort(),
            uses: [...uses].sort(),
            dynamic,
        })}\n`,
    );
}
