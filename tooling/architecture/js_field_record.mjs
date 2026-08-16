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

function analyse(source) {
    const ast = espree.parse(source, PARSE);
    const aliases = recordAliases(ast);
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
