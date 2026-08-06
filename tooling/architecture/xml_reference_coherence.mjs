/**
 * Provider extraction for `xml_reference_coherence.py`.
 *
 * Answers one question per JS file: which literal keys does it register into
 * the registries that view-arch XML names by string — `fields` (`widget="…"`
 * in record views), `views` (`js_class="…"`), `view_widgets`
 * (`<widget name="…"/>`), `formatters` (`widget="…"` in pivot/graph/cohort
 * archs) and `grid_components` (`widget="…"` in grid archs)?
 *
 * Parsed with espree rather than matched with a regex, for the reason
 * `js_service_shape.mjs` already records: the registration forms nest and
 * alias. Three forms register keys in this tree and a regex over the inline
 * form alone misses two of them:
 *
 *   1. inline    registry.category("fields").add("key", …)
 *   2. bound     const r = registry.category("views"); r.add("key", …)
 *                — including chained `r.add("a", …).add("b", …)`
 *   3. helper    registerField("key", …) / registerFallbackField("key", …)
 *                and the spec-object form
 *                registerField({ name, view?, aliases? }, …), this fork's
 *                canonical field registration (`fields/_registry.js`), whose
 *                key is `view ? `${view}.${name}` : name` plus every alias.
 *
 * A key that is not a string literal (a computed name, a spread spec) cannot
 * be enumerated; it is emitted as `dynamic` so the caller can COUNT it as
 * unverifiable rather than silently narrowing the provider set.
 *
 * Emits one JSON object per line:
 *   {kind: "provider", category, key, file}
 *   {kind: "dynamic", category, file, line}
 */
import { readFileSync } from "node:fs";
import * as espree from "espree";

const PARSE = { ecmaVersion: "latest", sourceType: "module", loc: true };
const CATEGORIES = new Set([
    "fields",
    "views",
    "view_widgets",
    "formatters",
    "grid_components",
]);
const REGISTER_HELPERS = new Set(["registerField", "registerFallbackField"]);

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

/** `registry.category("<governed>")` (any callee object), or null. */
function categoryOf(call) {
    if (
        call?.type === "CallExpression" &&
        call.callee.type === "MemberExpression" &&
        call.callee.property.name === "category" &&
        call.arguments[0]?.type === "Literal" &&
        CATEGORIES.has(call.arguments[0].value)
    ) {
        return call.arguments[0].value;
    }
    return null;
}

/** Object-literal property value by key name, or undefined. */
function propValue(obj, name) {
    const p = obj.properties.find(
        (q) =>
            q.type === "Property" &&
            !q.computed &&
            (q.key.name ?? q.key.value) === name,
    );
    return p?.value;
}

/**
 * The keys a `registerField(nameOrSpec, …)` call registers — the same
 * expansion `fields/_registry.js` performs at runtime — or null when the
 * spec is not statically enumerable.
 */
function fieldSpecKeys(arg) {
    if (arg.type === "Literal" && typeof arg.value === "string") {
        return [arg.value];
    }
    if (arg.type !== "ObjectExpression") {
        return null;
    }
    const keyOf = (spec) => {
        const name = propValue(spec, "name");
        if (name?.type !== "Literal" || typeof name.value !== "string") {
            return null;
        }
        const view = propValue(spec, "view");
        if (view === undefined) {
            return name.value;
        }
        if (view.type !== "Literal" || typeof view.value !== "string") {
            return null;
        }
        return `${view.value}.${name.value}`;
    };
    const main = keyOf(arg);
    if (main === null) {
        return null;
    }
    const keys = [main];
    const aliases = propValue(arg, "aliases");
    if (aliases === undefined) {
        return keys;
    }
    if (aliases.type !== "ArrayExpression") {
        return null;
    }
    for (const alias of aliases.elements) {
        if (alias?.type === "Literal" && typeof alias.value === "string") {
            keys.push(alias.value);
        } else if (alias?.type === "ObjectExpression") {
            const k = keyOf(alias);
            if (k === null) {
                return null;
            }
            keys.push(k);
        } else {
            return null;
        }
    }
    return keys;
}

for (const file of process.argv.slice(2)) {
    let ast;
    try {
        ast = espree.parse(readFileSync(file, "utf8"), PARSE);
    } catch {
        continue; // a file ESLint would reject anyway; not this gate's report to make
    }
    const out = [];
    const emit = (category, key) => out.push({ kind: "provider", category, key, file });
    const dynamic = (category, node) =>
        out.push({ kind: "dynamic", category, file, line: node.loc.start.line });

    // Bound form: `const r = registry.category("views")`.
    const bindings = new Map();
    walk(ast, (n) => {
        if (n.type === "VariableDeclarator" && n.id.type === "Identifier") {
            const cat = categoryOf(n.init);
            if (cat) {
                bindings.set(n.id.name, cat);
            }
        }
    });

    walk(ast, (n) => {
        if (n.type !== "CallExpression") {
            return;
        }
        // registerField("…") / registerField({ name, view, aliases }) — the
        // helper always targets the `fields` category.
        if (n.callee.type === "Identifier" && REGISTER_HELPERS.has(n.callee.name)) {
            const keys = n.arguments.length ? fieldSpecKeys(n.arguments[0]) : null;
            if (keys === null) {
                dynamic("fields", n);
            } else {
                keys.forEach((k) => emit("fields", k));
            }
            return;
        }
        // `.add(key, …)` whose receiver is a governed category: the inline
        // form, the bound form, and — because `.add()` returns the registry —
        // any chained `.add()` hanging off either.
        if (n.callee.type !== "MemberExpression" || n.callee.property.name !== "add") {
            return;
        }
        let target = n.callee.object;
        while (
            target.type === "CallExpression" &&
            target.callee.type === "MemberExpression" &&
            target.callee.property.name === "add"
        ) {
            target = target.callee.object; // unwind a chain to its receiver
        }
        const category =
            target.type === "Identifier"
                ? (bindings.get(target.name) ?? null)
                : categoryOf(target);
        if (!category) {
            return;
        }
        const keyArg = n.arguments[0];
        if (keyArg?.type === "Literal" && typeof keyArg.value === "string") {
            emit(category, keyArg.value);
        } else {
            dynamic(category, n);
        }
    });

    for (const rec of out) {
        process.stdout.write(JSON.stringify(rec) + "\n");
    }
}
