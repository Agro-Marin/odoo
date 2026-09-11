import assert from "node:assert/strict";
import { dirname, resolve } from "node:path";
import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import test from "node:test";

import ts from "typescript";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");

test("mail contracts preserve model, collection, and utility types", () => {
    const configPath = resolve(root, "tsconfig.strict.json");
    const loaded = ts.readConfigFile(configPath, ts.sys.readFile);
    assert.equal(loaded.error, undefined);
    const config = ts.parseJsonConfigFileContent(loaded.config, ts.sys, root);
    assert.deepEqual(config.errors, []);
    const fixture = resolve(root, "tooling/typecheck/mail_contracts.ts");
    const source = `
import { fields } from "@mail/model/misc";
import { RecordList } from "@mail/model/record_list";
import { assignDefined, assignIn, nearestGreaterThanOrEqual } from "@mail/utils/common/misc";
import { ActionParams } from "@mail/core/common/action";
import { Thread } from "models";

const assigned = assignDefined({ count: 1 }, { count: 2 });
assigned.count.toFixed();
// @ts-expect-error Assignment helpers preserve the target shape.
assigned.missing;
const merged = assignIn({ label: "mail" }, { label: "discuss" });
merged.label.toUpperCase();
// @ts-expect-error Assignment does not erase the target's property types.
merged.label.toFixed();
const nearest = nearestGreaterThanOrEqual([{ id: 1 }], 1, item => item.id);
nearest?.id.toFixed();
// @ts-expect-error Search preserves its element type.
nearest?.missing;

const thread = fields.One("Thread");
const typedThread: Thread = thread;
// @ts-expect-error A model relation is not a scalar.
const scalar: number = thread;
const threads = fields.Many("Thread");
const list: RecordList<Thread> = threads;
threads.add(typedThread);
// @ts-expect-error Relations retain their element type.
threads[0].missing;
const numericThread = threads.find((thread): thread is Thread & {id: number} => typeof thread.id === "number");
numericThread?.id.toFixed();
// @ts-expect-error A predicate narrows the selected record ID.
numericThread?.id.toUpperCase();
declare const action: ActionParams<Thread>;
const owner: Thread = action.owner;
// @ts-expect-error Action callbacks retain their owner's model.
action.owner.missing;
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
        diagnostics.map((diagnostic) =>
            ts.flattenDiagnosticMessageText(diagnostic.messageText, " "),
        ),
        [],
    );
});

test("every mail browser source and test is included, opted in, and type-clean", () => {
    const loaded = ts.readConfigFile(resolve(root, "tsconfig.json"), ts.sys.readFile);
    assert.equal(loaded.error, undefined);
    const config = ts.parseJsonConfigFileContent(loaded.config, ts.sys, root);
    assert.deepEqual(config.errors, []);
    const program = ts.createProgram(config.fileNames, config.options);
    const files = ["src", "tests"].flatMap((directory) => {
        const base = resolve(root, "addons/mail/static", directory);
        return readdirSync(base, { recursive: true })
            .filter(
                (file) =>
                    file.endsWith(".js") &&
                    !(directory === "src" && file === "service_worker.js"),
            )
            .map((file) => resolve(base, file));
    });
    assert.ok(files.length > 600, "check the full mail browser tree");
    const diagnostics = [];
    for (const path of files) {
        assert.match(readFileSync(path, "utf8"), /^\s*\/\/\s*@ts-check\b/m, path);
        const file = program.getSourceFile(path);
        assert.ok(file, `${path} must be included in the browser program`);
        diagnostics.push(
            ...program.getSyntacticDiagnostics(file),
            ...program.getSemanticDiagnostics(file),
        );
    }
    assert.equal(
        diagnostics.length,
        0,
        ts.formatDiagnosticsWithColorAndContext(diagnostics, {
            getCanonicalFileName: (file) => file,
            getCurrentDirectory: () => root,
            getNewLine: () => "\n",
        }),
    );
});
