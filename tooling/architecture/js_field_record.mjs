import { readFileSync } from "node:fs";
import * as espree from "espree";

const PARSE = { ecmaVersion: "latest", sourceType: "module", loc: true };

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

function isPropsObject(node) {
    if (node?.type === "Identifier") {
        return node.name === "props";
    }
    return (
        node?.type === "MemberExpression" &&
        !node.computed &&
        node.property?.name === "props"
    );
}

function isPropsRecord(node) {
    return (
        node?.type === "MemberExpression" &&
        !node.computed &&
        node.property?.name === "record" &&
        isPropsObject(node.object)
    );
}

function isPropsMember(node) {
    return (
        node?.type === "MemberExpression" &&
        !node.computed &&
        node.property?.type === "Identifier" &&
        isPropsObject(node.object)
    );
}

function isPropsName(node) {
    return (
        node?.type === "MemberExpression" &&
        !node.computed &&
        node.property?.name === "name" &&
        isPropsObject(node.object)
    );
}

function destructuredMembers(ast, isRecord) {
    const names = new Set();
    walk(ast, (node) => {
        if (node.type !== "VariableDeclarator" || node.id.type !== "ObjectPattern") {
            return;
        }
        if (!isRecord(node.init)) {
            return;
        }
        for (const prop of node.id.properties) {
            if (prop.type === "Property" && !prop.computed) {
                const name = prop.key?.name ?? prop.key?.value;
                if (typeof name === "string") {
                    names.add(name);
                }
            }
        }
    });
    return names;
}

/**
 * The record a callback is *handed* rather than one reachable from `this.props`.
 *
 * Three shapes, and only three, so that a `.map((record) => …)` over an RPC
 * result is not mistaken for one:
 *
 *   - a registry descriptor's `isEmpty(record, …)` / `isValid(record, …)`,
 *   - `useRecordObserver((record, props) => …)`.
 *
 * Without these the contract was open in a way its own report showed and its
 * gate did not: the *count* of such reads is pinned, so a new one fails, but
 * swapping one existing read for a different member kept the count and passed
 * silently. `dateRangeField.isValid` reached `record.activeFields` -- a member
 * `FIELD_RECORD_SURFACE` does not declare -- entirely undetected.
 */
const HANDED_RECORD_PROPERTIES = new Set(["isEmpty", "isValid"]);
const HANDED_RECORD_CALLS = new Set(["useRecordObserver"]);

/**
 * @param {any} ast
 * @returns {Set<string>}
 */
function handedRecordAliases(ast) {
    const names = new Set();
    const firstParamName = (fn) => {
        const param = fn?.params?.[0];
        return param?.type === "Identifier" ? param.name : undefined;
    };
    walk(ast, (node) => {
        if (
            node.type === "Property" &&
            !node.computed &&
            HANDED_RECORD_PROPERTIES.has(node.key?.name) &&
            /Function/.test(node.value?.type || "")
        ) {
            const name = firstParamName(node.value);
            if (name) {
                names.add(name);
            }
        }
        if (
            node.type === "CallExpression" &&
            HANDED_RECORD_CALLS.has(node.callee?.name)
        ) {
            const name = firstParamName(node.arguments?.[0]);
            if (name) {
                names.add(name);
            }
        }
    });
    return names;
}

function recordAliases(ast) {
    const aliases = new Set();
    walk(ast, (node) => {
        if (node.type !== "VariableDeclarator" || !node.init) {
            return;
        }
        if (isPropsRecord(node.init) && node.id.type === "Identifier") {
            aliases.add(node.id.name);
            return;
        }
        const fromProps =
            (node.init.type === "MemberExpression" &&
                !node.init.computed &&
                node.init.property?.name === "props") ||
            (node.init.type === "Identifier" && node.init.name === "props");
        if (fromProps && node.id.type === "ObjectPattern") {
            for (const prop of node.id.properties) {
                if (prop.type === "Property" && prop.key?.name === "record") {
                    aliases.add(prop.value?.name ?? "record");
                }
            }
        }
    });
    return aliases;
}

/**
 * Own members of every class declared in the file, keyed by class name.
 *
 * The gate's argument opens with the size of what `standardFieldProps` hands
 * out, and that figure was prose: it said 83 against a `RelationalRecord` that
 * declares 81, in the module docstring and again in `doc/architecture/gates.md`.
 * Reported here so the MEASURED block can carry it, because this is the only
 * pass in the gate that owns a real JS parser -- counting members by regex is
 * the mistake WHY AN AST PASS was written about.
 *
 * Own members only: no base class is followed, which is what "before anything
 * inherited" means. A computed key names no member at parse time and is skipped.
 */
function classMembers(ast) {
    const byClass = {};
    walk(ast, (node) => {
        if (node.type !== "ClassDeclaration" && node.type !== "ClassExpression") {
            return;
        }
        const name = node.id?.name;
        if (!name) {
            return;
        }
        const names = new Set();
        for (const member of node.body.body) {
            if (member.computed || !member.key) {
                continue;
            }
            const key = member.key.name ?? member.key.value;
            if (key !== undefined) {
                names.add(String(key));
            }
        }
        byClass[name] = [...names].sort();
    });
    return byClass;
}

function analyse(source) {
    const ast = espree.parse(source, PARSE);
    const aliases = recordAliases(ast);
    for (const name of handedRecordAliases(ast)) {
        aliases.add(name);
    }
    const isRecord = (node) =>
        isPropsRecord(node) || (node?.type === "Identifier" && aliases.has(node.name));

    const members = destructuredMembers(ast, isRecord);
    const siblings = new Set();
    const propSiblings = new Set();
    let ownValue = 0;
    let dynamic = 0;
    let unresolved = 0;
    let isWidget = false;

    walk(ast, (node) => {
        if (node.type === "Identifier" && node.name === "standardFieldProps") {
            isWidget = true;
        }
        if (node.type !== "MemberExpression") {
            return;
        }
        if (!node.computed && isRecord(node.object) && node.property?.name) {
            members.add(node.property.name);
        }
        if (
            !node.computed &&
            node.object?.type === "Identifier" &&
            node.object.name === "record" &&
            !aliases.has("record")
        ) {
            unresolved += 1;
        }
        const base = node.object;
        const isRecordData =
            base?.type === "MemberExpression" &&
            !base.computed &&
            base.property?.name === "data" &&
            isRecord(base.object);
        if (!isRecordData) {
            return;
        }
        if (!node.computed) {
            siblings.add(node.property.name);
            return;
        }
        const key = node.property;
        if (
            isPropsName(key) ||
            (key.type === "Identifier" && /^(name|fieldName)$/.test(key.name))
        ) {
            ownValue += 1;
        } else if (key.type === "Literal" && typeof key.value === "string") {
            siblings.add(key.value);
        } else if (isPropsMember(key)) {
            propSiblings.add(key.property.name);
        } else {
            dynamic += 1;
        }
    });

    return {
        isWidget,
        members: [...members].sort(),
        siblings: [...siblings].sort(),
        propSiblings: [...propSiblings].sort(),
        classes: classMembers(ast),
        ownValue,
        dynamic,
        unresolved,
    };
}

for (const file of process.argv.slice(2)) {
    let result;
    try {
        result = analyse(readFileSync(file, "utf8"));
    } catch (error) {
        process.stderr.write(`parse failed: ${file}: ${error.message}\n`);
        process.exitCode = 1;
        continue;
    }
    process.stdout.write(`${JSON.stringify({ file, ...result })}\n`);
}
