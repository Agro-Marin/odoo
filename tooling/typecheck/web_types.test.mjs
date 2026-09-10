import assert from "node:assert/strict";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import ts from "typescript";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const webSource = resolve(root, "addons/web/static/src") + "/";

for (const configName of ["tsconfig.json", "tsconfig.serviceworker.web.json"]) {
    test(`web source types pass ${configName}`, () => {
        const configPath = resolve(root, configName);
        const loaded = ts.readConfigFile(configPath, ts.sys.readFile);
        assert.equal(loaded.error, undefined);
        const config = ts.parseJsonConfigFileContent(loaded.config, ts.sys, root);
        assert.deepEqual(config.errors, []);
        const program = ts.createProgram({
            rootNames: config.fileNames.filter(
                (file) => file.startsWith(webSource) || file.endsWith(".d.ts"),
            ),
            options: config.options,
        });
        const sources = program
            .getSourceFiles()
            .filter(
                (file) =>
                    file.fileName.startsWith(webSource) && !file.isDeclarationFile,
            );
        assert.ok(sources.length > 0);
        const diagnostics = sources.flatMap((file) => [
            ...program.getSyntacticDiagnostics(file),
            ...program.getSemanticDiagnostics(file),
        ]);
        assert.deepEqual(
            diagnostics.map((diagnostic) => {
                const { line, character } =
                    diagnostic.file.getLineAndCharacterOfPosition(diagnostic.start);
                const message = ts.flattenDiagnosticMessageText(
                    diagnostic.messageText,
                    " ",
                );
                return `${diagnostic.file.fileName}:${line + 1}:${character + 1}: ${message}`;
            }),
            [],
        );
    });
}
