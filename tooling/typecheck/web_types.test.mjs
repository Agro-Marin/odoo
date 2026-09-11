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
            rootNames: config.fileNames,
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

test("web utility contracts preserve arguments, absence, and promise identity", () => {
    const loaded = ts.readConfigFile(
        resolve(root, "tsconfig.strict.json"),
        ts.sys.readFile,
    );
    assert.equal(loaded.error, undefined);
    const config = ts.parseJsonConfigFileContent(loaded.config, ts.sys, root);
    assert.deepEqual(config.errors, []);
    config.options.noImplicitAny = true;
    const fixture = resolve(root, "tooling/typecheck/web_contracts.ts");
    const source = `
import { ensureArray, zip, zipWith } from "@web/core/utils/collections/arrays";
import { Cache } from "@web/core/utils/collections/cache";
import { InFlight } from "@web/core/utils/concurrency";

const absent: undefined[] = ensureArray();
const scalar: "abc"[] = ensureArray("abc" as const);
const elements: number[] = ensureArray(new Set([1, 2]));
const mixed: (number | undefined)[] = ensureArray(Math.random() ? [1] : undefined);
// @ts-expect-error An omitted value produces undefined, not an arbitrary element type.
const missingNumber: number[] = ensureArray();
// @ts-expect-error Strings are wrapped intact rather than split into characters.
const character: "a"[] = ensureArray("abc" as const);
zip([1], ["a"])[0][0].toFixed();
zip([1], ["a"], false)[0][1].toUpperCase();
const padded = zip([1, 2], ["a"], true);
padded[0][0]?.toFixed();
padded[0][1]?.toUpperCase();
// @ts-expect-error The first iterable can be shorter.
padded[0][0].toFixed();
// @ts-expect-error The second iterable can be shorter.
padded[0][1].toUpperCase();
const dynamic = zip([1], ["a"], Math.random() > 0.5);
// @ts-expect-error A runtime padding flag also requires handling missing values.
dynamic[0][1].toUpperCase();
zipWith([1], ["a"], (n, s) => n.toFixed() + s.toUpperCase());

const cache = new Cache((id: number, prefix: string) => prefix + id);
cache.read(1, "item").toUpperCase();
cache.set("cached", 1, "item");
cache.clear(1, "item");
cache.read(1, "item", "extra key");
new Cache(() => 42).read("key ignored by loader");
// @ts-expect-error Reads require the loader's argument types.
cache.read("wrong", "item");
// @ts-expect-error Reads require all loader arguments.
cache.read(1);
// @ts-expect-error Writes use the same lookup path as reads.
cache.set("cached", "wrong", "item");
// @ts-expect-error Clears use the same lookup path as reads.
cache.clear("wrong", "item");
// @ts-expect-error Cached values retain the loader's result type.
cache.set(12, 1, "item");
new Cache((id: number) => id, (id: number) => String(id));
// @ts-expect-error Custom keys must accept the loader's arguments.
new Cache((id: number) => id, (id: string) => id);
const pending = Object.assign(Promise.resolve(42), { abort() {} });
const tracked = new InFlight().track(pending);
tracked.abort();
tracked.then(value => value.toFixed());
// @ts-expect-error Tracking preserves the promise's result type.
tracked.then(value => value.toUpperCase());
`;
    const host = ts.createCompilerHost(config.options);
    const getSourceFile = host.getSourceFile.bind(host);
    host.getSourceFile = (file, languageVersion, ...args) =>
        file === fixture
            ? ts.createSourceFile(file, source, languageVersion, true)
            : getSourceFile(file, languageVersion, ...args);
    const program = ts.createProgram({
        rootNames: [...config.fileNames, fixture],
        options: config.options,
        host,
    });
    const file = program.getSourceFile(fixture);
    assert.ok(file);
    const diagnostics = [
        ...program.getSyntacticDiagnostics(file),
        ...program.getSemanticDiagnostics(file),
    ];
    assert.deepEqual(
        diagnostics.map(
            (diagnostic) =>
                `${file.getLineAndCharacterOfPosition(diagnostic.start).line + 1}: ${ts.flattenDiagnosticMessageText(diagnostic.messageText, " ")}`,
        ),
        [],
    );
});
