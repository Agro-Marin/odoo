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
