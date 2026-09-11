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
    config.options.noImplicitAny = true;
    const fixture = resolve(root, "tooling/typecheck/mail_contracts.ts");
    const source = `
import { fields } from "@mail/model/misc";
import { RecordList } from "@mail/model/record_list";
import { assignDefined, assignIn, nearestGreaterThanOrEqual, makeSequential } from "@mail/utils/common/misc";
import { ActionParams } from "@mail/core/common/action";
import { Thread } from "models";

// @ts-expect-error Literal model names must exist in the assembled registry.
fields.One("Thraed");
// @ts-expect-error Collection relations reject misspelled model names too.
fields.Many("Thraed");
let computedFlag = fields.Attr(false, { compute() { return true; } });
computedFlag = true;
// @ts-expect-error A numeric attribute cannot compute a string.
fields.Attr(0, { compute() { return "not a number"; } });
// @ts-expect-error A relation cannot compute an unrelated scalar.
fields.One("Thread", { compute() { return 123; } });
// @ts-expect-error Date fields compute dates, not serialized strings.
fields.Date({ compute() { return "not a date"; } });
fields.Attr(0, { compute() {
    // @ts-expect-error An unspecified receiver is not any.
    return this.doesNotExist();
} });
declare const store: import("models").Store;
store.Thread.insert({id: 1, model: "discuss.channel"});
store.Thread.insert([{id: 1, model: "discuss.channel"}]);
// @ts-expect-error Known model inserts reject unknown client-side keys.
store.Thread.insert({id: 1, model: "discuss.channel", doesNotExist: 5});
// @ts-expect-error Batch inserts validate keys too.
store.Thread.insert([{id: 1, model: "discuss.channel", doesNotExist: 5}]);
const updateResult = store.MAKE_UPDATE(() => ({ count: 1 }));
updateResult.count.toFixed();
// @ts-expect-error Updates preserve the callback result rather than returning any.
updateResult.missing;
const updatePromise = store.MAKE_UPDATE(() => Promise.resolve("done"));
updatePromise.then(value => value.toUpperCase());
// @ts-expect-error Update callbacks retain their asynchronous result type too.
updatePromise.then(value => value.toFixed());
const byLocalId = store.get("Thread,missing");
byLocalId?.localId.toUpperCase();
// @ts-expect-error Local-ID lookup can miss, just like model-specific lookup.
byLocalId.localId.toUpperCase();
declare const queueRecord: Thread;
store._.ADD_QUEUE("compute", queueRecord, "name");
store._.ADD_QUEUE("onAdd", queueRecord, "messages", queueRecord);
// @ts-expect-error Computation requests need a field name.
store._.ADD_QUEUE("compute", queueRecord);
// @ts-expect-error Relation callbacks need the related record.
store._.ADD_QUEUE("onAdd", queueRecord, "messages");
// @ts-expect-error Deletion requests do not accept a field name.
store._.ADD_QUEUE("delete", queueRecord, "messages");
// @ts-expect-error Callback queues contain callbacks, not records.
store._.RO_QUEUE.set(queueRecord, true);
const found = store.Thread.get({id: 1, model: "discuss.channel"});
found?.localId.toUpperCase();
// @ts-expect-error The store facade preserves missing-record nullability.
found.localId.toUpperCase();
declare const typedAction: import("@mail/core/common/action").Action<Thread>;
typedAction.icon?.toUpperCase();
// @ts-expect-error Action option results retain their value type.
typedAction.icon?.doesNotExist();
typedAction.sequence?.toFixed();
// @ts-expect-error Sequence is numeric.
typedAction.sequence?.toUpperCase();
const sequential = makeSequential();
const queued = sequential(async () => 42);
queued.then(value => {
    value?.toFixed();
    // @ts-expect-error Superseded operations resolve without a value.
    value.toFixed();
    // @ts-expect-error Each operation preserves its result type.
    value?.toUpperCase();
});
declare const update: import("@mail/discuss/call/common/peer_to_peer_types").PeerUpdate;
if (update.name === "track") {
    update.payload.track.stop();
    // @ts-expect-error Event names select the payload contract.
    update.payload.message;
}

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
threads.flat()[0].localId.toUpperCase();
// @ts-expect-error Flattening does not erase the model type.
threads.flat()[0].doesNotExist();
threads.add(typedThread);
// @ts-expect-error Relations retain their element type.
threads[0].missing;
const numericThread = threads.find((thread): thread is Thread & {id: number} => typeof thread.id === "number");
numericThread?.id.toFixed();
// @ts-expect-error A predicate narrows the selected record ID.
numericThread?.id.toUpperCase();
const numericThreads = threads.filter((thread): thread is Thread & {id: number} => typeof thread.id === "number");
numericThreads[0].id.toFixed();
// @ts-expect-error Filtering with a predicate preserves the narrowed ID type.
numericThreads[0].id.toUpperCase();
threads.filter(thread => thread.id)[0].localId.toUpperCase();
const names = threads.flatMap(thread => [thread.localId]);
names[0].toUpperCase();
// @ts-expect-error Flat mapping preserves the callback result type.
names[0].toFixed();
const readonlyNames = threads.flatMap(thread => [thread.localId] as readonly string[]);
readonlyNames[0].toUpperCase();
const count = threads.reduce((total, thread) => total + thread.localId.length, 0);
count.toFixed();
// @ts-expect-error A numeric accumulator is not a string.
count.toUpperCase();
const selected = threads.reduce((previous, current) => current);
selected.localId.toUpperCase();
// @ts-expect-error An unseeded reduction returns a record.
selected.missing;
const grouped = threads.reduceRight((result, thread) => {
    result.push(thread.localId);
    return result;
}, [] as string[]);
grouped[0].toUpperCase();
// @ts-expect-error A seeded reduction retains its accumulator's element type.
grouped[0].toFixed();
const lastSelected = threads.reduceRight((previous, current) => current);
lastSelected.localId.toUpperCase();
// @ts-expect-error An unseeded right reduction returns a record.
lastSelected.missing;
// @ts-expect-error The callback must return the accumulator type.
threads.reduce((total, thread) => thread.localId, 0);
// @ts-expect-error The right-reduction callback must return the accumulator type.
threads.reduceRight((total, thread) => thread.localId, 0);
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
        diagnostics.map(
            (diagnostic) =>
                `${file.getLineAndCharacterOfPosition(diagnostic.start).line + 1}: ${ts.flattenDiagnosticMessageText(diagnostic.messageText, " ")}`,
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

test("mail service worker stays clean in its worker program", () => {
    const loaded = ts.readConfigFile(
        resolve(root, "tsconfig.serviceworker.web.json"),
        ts.sys.readFile,
    );
    assert.equal(loaded.error, undefined);
    const config = ts.parseJsonConfigFileContent(loaded.config, ts.sys, root);
    assert.deepEqual(config.errors, []);
    assert.equal(config.options.checkJs, true);
    assert.equal(config.options.strictNullChecks, true);
    assert.equal(config.options.noImplicitAny, true);
    const program = ts.createProgram(config.fileNames, config.options);
    const worker = program.getSourceFile(
        resolve(root, "addons/mail/static/src/service_worker.js"),
    );
    assert.ok(worker, "mail worker must remain included in the worker program");
    const diagnostics = ts.getPreEmitDiagnostics(program);
    assert.deepEqual(
        diagnostics.map((d) => ts.flattenDiagnosticMessageText(d.messageText, " ")),
        [],
    );
});

test("mail store construction, metadata and queues pass both strict checks", () => {
    const loaded = ts.readConfigFile(resolve(root, "tsconfig.json"), ts.sys.readFile);
    assert.equal(loaded.error, undefined);
    const config = ts.parseJsonConfigFileContent(loaded.config, ts.sys, root);
    assert.deepEqual(config.errors, []);
    const program = ts.createProgram(config.fileNames, {
        ...config.options,
        checkJs: true,
        noImplicitAny: true,
        strictNullChecks: true,
    });
    const locked = [
        "make_store",
        "misc",
        "model_internal",
        "record_internal",
        "record_uses",
        "store",
        "store_internal",
    ];
    const diagnostics = locked.flatMap((name) => {
        const file = program.getSourceFile(
            resolve(root, `addons/mail/static/src/model/${name}.js`),
        );
        assert.ok(file, `${name} must remain included`);
        return [
            ...program.getSyntacticDiagnostics(file),
            ...program.getSemanticDiagnostics(file),
        ];
    });
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
