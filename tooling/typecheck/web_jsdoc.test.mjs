import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import test from "node:test";

import ts from "typescript";

const root = new URL("../../addons/web/static/", import.meta.url);

function diagnostics(file, source) {
    const parsed = ts.createSourceFile(
        file,
        source,
        ts.ScriptTarget.Latest,
        true,
        ts.ScriptKind.JS,
    );
    return (parsed.jsDocDiagnostics ?? []).map((diagnostic) => {
        const { line, character } = parsed.getLineAndCharacterOfPosition(
            diagnostic.start,
        );
        const message = ts.flattenDiagnosticMessageText(diagnostic.messageText, " ");
        return `${file}:${line + 1}:${character + 1}: ${message}`;
    });
}

test("web JSDoc types parse in source, tests, and HOOT", () => {
    const failures = [];
    let count = 0;
    for (const directory of ["src/", "tests/", "lib/hoot/", "lib/hoot-dom/"]) {
        const base = new URL(directory, root);
        for (const file of readdirSync(base, { recursive: true })) {
            if (!file.endsWith(".js")) {
                continue;
            }
            const path = new URL(file, base);
            failures.push(
                ...diagnostics(fileURLToPath(path), readFileSync(path, "utf8")),
            );
            count++;
        }
    }
    assert.ok(count > 0);
    assert.deepEqual(failures, []);
});

test("the parser rejects stripped type bodies and template names", () => {
    for (const annotation of ["@typedef {{", "@template", "@param {{", "@returns {{"]) {
        const source = `/** ${annotation} */\nfunction example(value) { return value; }`;
        assert.ok(diagnostics("example.js", source).length > 0, annotation);
    }
});
