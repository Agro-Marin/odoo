import { readFileSync } from "node:fs";
import * as espree from "espree";

const PARSE = {
    ecmaVersion: "latest",
    sourceType: "module",
    loc: true,
    comment: true,
};

/**
 * Lines the class body occupies, less the ones that carry only a comment.
 *
 * The JS function-length budget runs eslint with `skipComments: true`, and a
 * class budget that counted them would price a documented class above an
 * undocumented one of the same mass. Same accounting, so the two numbers stay
 * comparable.
 */
function codeLines(node, comments, sourceLines) {
    const first = node.loc.start.line;
    const last = node.loc.end.line;
    const blanked = new Map();
    for (const c of comments) {
        if (c.loc.end.line < first || c.loc.start.line > last) {
            continue;
        }
        for (let ln = c.loc.start.line; ln <= c.loc.end.line; ln++) {
            if (ln < first || ln > last) {
                continue;
            }
            const text = blanked.get(ln) ?? sourceLines[ln - 1] ?? "";
            const from = ln === c.loc.start.line ? c.loc.start.column : 0;
            const to = ln === c.loc.end.line ? c.loc.end.column : text.length;
            blanked.set(
                ln,
                text.slice(0, from) +
                    " ".repeat(Math.max(0, to - from)) +
                    text.slice(to),
            );
        }
    }
    let commentOnly = 0;
    for (const [, text] of blanked) {
        if (text.trim() === "") {
            commentOnly++;
        }
    }
    return last - first + 1 - commentOnly;
}

function walk(node, fn, parent = null) {
    if (!node || typeof node.type !== "string") {
        return;
    }
    fn(node, parent);
    for (const key of Object.keys(node)) {
        if (key === "loc" || key === "range" || key === "parent") {
            continue;
        }
        const child = node[key];
        if (Array.isArray(child)) {
            child.forEach((c) => walk(c, fn, node));
        } else if (child && typeof child.type === "string") {
            walk(child, fn, node);
        }
    }
}

/**
 * What to call a class in the report.
 *
 * A class expression carries no `id`, so an anonymous one is named after what
 * it is bound to -- `const Foo = class extends Bar {}`, `patch(X, class {})`,
 * a mixin factory's return. A finding nobody can locate is not worth printing.
 */
function className(node, parent) {
    if (node.id?.name) {
        return node.id.name;
    }
    if (parent?.type === "VariableDeclarator" && parent.id?.type === "Identifier") {
        return parent.id.name;
    }
    if (parent?.type === "AssignmentExpression" && parent.left?.type === "Identifier") {
        return parent.left.name;
    }
    if (
        (parent?.type === "PropertyDefinition" || parent?.type === "Property") &&
        parent.key?.name
    ) {
        return parent.key.name;
    }
    if (parent?.type === "ExportDefaultDeclaration") {
        return "(default export)";
    }
    return "(anonymous class)";
}

for (const file of process.argv.slice(2)) {
    const source = readFileSync(file, "utf8");
    const sourceLines = source.split("\n");
    let ast;
    try {
        ast = espree.parse(source, PARSE);
    } catch (error) {
        process.stderr.write(`${file}: ${error.message}\n`);
        process.exitCode = 1;
        continue;
    }
    walk(ast, (node, parent) => {
        if (node.type !== "ClassDeclaration" && node.type !== "ClassExpression") {
            return;
        }
        process.stdout.write(
            JSON.stringify({
                file,
                line: node.loc.start.line,
                lines: codeLines(node, ast.comments, sourceLines),
                what: className(node, parent),
            }) + "\n",
        );
    });
}
