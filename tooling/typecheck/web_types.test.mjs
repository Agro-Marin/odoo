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
    config.options.strictBindCallApply = true;
    const fixture = resolve(root, "tooling/typecheck/web_contracts.ts");
    const source = `
import { cartesian, ensureArray, groupBy, intersection, symmetricalDifference, zip, zipWith } from "@web/core/utils/collections/arrays";
import { Cache } from "@web/core/utils/collections/cache";
import { Deferred, InFlight } from "@web/core/utils/concurrency";
import { LruCache } from "@web/core/utils/lru_cache";
import { nameService, ERROR_INACCESSIBLE_OR_MISSING } from "@web/core/name_service";
import { debounce, throttleForAnimation, useDebounced, useThrottleForAnimation } from "@web/core/utils/timing";

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

const debounced = debounce((n: number) => n * 2, 100);
const throttled = throttleForAnimation((n: number) => n * 2);
const debouncedHook = useDebounced((n: number) => n * 2, 100);
const throttledHook = useThrottleForAnimation((n: number) => n * 2);
for (const schedule of [debounced, throttled, debouncedHook, throttledHook]) {
    const result: Promise<number | undefined> = schedule(1);
    result.then(value => value?.toFixed());
    schedule.cancel();
    // @ts-expect-error Scheduling preserves the callback argument type.
    schedule("wrong");
}
// @ts-expect-error Cancelling a pending debounce resolves without a callback value.
const definiteDebounce: Promise<number> = debounced(1);
// @ts-expect-error The debounce hook also exposes cancellation.
const definiteDebounceHook: Promise<number> = debouncedHook(1);
// @ts-expect-error Throttling always returns a promise, including synchronous callbacks.
const syncThrottle: number = throttled(1);
// @ts-expect-error Superseded throttle calls resolve without a callback value.
const definiteThrottle: Promise<number> = throttled(1);
// @ts-expect-error The throttle hook also returns a promise.
const syncThrottleHook: number = throttledHook(1);
// @ts-expect-error The throttle hook also exposes cancellation.
const definiteThrottleHook: Promise<number> = throttledHook(1);
const asyncThrottle = throttleForAnimation(async (n: number) => n);
asyncThrottle(1).then(value => {
    value?.toFixed();
    // @ts-expect-error Async callbacks are awaited but can still be superseded.
    value.toFixed();
});
const withProperty = Object.assign((n: number) => n, { custom: true });
// @ts-expect-error The wrapper does not copy properties from its callback.
throttleForAnimation(withProperty).custom;
function method(this: { base: number }, n: number) { return this.base + n; }
const methodThrottle = throttleForAnimation(method);
methodThrottle.call({ base: 1 }, 2);
// @ts-expect-error Standalone wrappers preserve an explicit callback receiver.
methodThrottle(2);
// @ts-expect-error The receiver must have the callback's shape.
methodThrottle.call({ unrelated: true }, 2);
useThrottleForAnimation(method)(2);
useDebounced(method, 100)(2);

const numberDeferred = new Deferred<number>();
numberDeferred.resolve(42);
numberDeferred.resolve(Promise.resolve(42));
numberDeferred.then(value => value.toFixed());
// @ts-expect-error A numeric promise must not resolve without a value.
numberDeferred.resolve();
// @ts-expect-error A numeric promise rejects a wrong scalar type.
numberDeferred.resolve("wrong");
// @ts-expect-error Adopted promises must resolve to the same value type.
numberDeferred.resolve(Promise.resolve("wrong"));
new Deferred<void>().resolve();
new Deferred<number | undefined>().resolve();
new Deferred().resolve();

groupBy(["a"], null).a?.[0].toUpperCase();
const grouped = groupBy([1, 2], (n): "odd" | "even" => n % 2 ? "odd" : "even");
grouped.odd?.[0].toFixed();
// @ts-expect-error A possible group is not necessarily present in the input.
grouped.even[0].toFixed();
// @ts-expect-error A literal criterion restricts the possible group names.
grouped.unrelated;
const booleans = groupBy([1, 2], n => n > 1);
booleans.true?.[0].toFixed();
booleans.false?.[0].toFixed();
const numericGroups = groupBy(["a"], (): 42 => 42);
numericGroups["42"]?.[0].toUpperCase();
const symbol = Symbol("group");
const symbols = groupBy([1], () => symbol);
symbols[String(symbol)]?.[0].toFixed();
// @ts-expect-error Symbols are stringified rather than preserved as symbol keys.
symbols[symbol];
const objects = groupBy([1], () => ({ toString: () => "key" }));
objects.key?.[0].toFixed();
groupBy([1], () => null).null?.[0].toFixed();
groupBy([1], () => undefined).undefined?.[0].toFixed();

const noProduct: undefined[] = cartesian();
const flatProduct: number[] = cartesian([1, 2]);
const pairProduct: [number, string][] = cartesian([1, 2], ["a", "b"]);
const readonlyProduct: [1 | 2, "a", boolean][] = cartesian([1, 2] as const, ["a"] as const, [true, false]);
pairProduct[0][0].toFixed();
pairProduct[0][1].toUpperCase();
// @ts-expect-error Tuple positions do not widen to the union of all element types.
pairProduct[0][0].toUpperCase();
const inferredProduct = cartesian([1], ["a"]);
// @ts-expect-error The inferred second tuple position remains a string.
inferredProduct[0][1].toFixed();
const dynamicInputs: number[][] = Math.random() ? [[1], [2]] : [];
const dynamicProduct = cartesian(...dynamicInputs);
// @ts-expect-error Dynamic arity can produce a sentinel, flat items, or tuples.
const certainTuples: number[][] = dynamicProduct;
const overlaps = intersection([1, "a"], new Set(["a", "b"]));
overlaps[0].toUpperCase();
// @ts-expect-error The intersection contains only types shared by both inputs.
overlaps[0].toFixed();
const disjoint: never[] = intersection([1], ["a"]);
const different = symmetricalDifference([1], ["a"]);
const combined: (number | string)[] = different;
// @ts-expect-error The difference may contain elements from either input.
const numericDifference: number[] = different;

const lru = new LruCache<number>(2, {
    onEvict(key, value) { key.toUpperCase(); value.toFixed(); },
});
lru.set("one", 1).set("two", 2);
lru.get("one")?.toFixed();
lru.peek("two")?.toFixed();
// @ts-expect-error Misses return undefined, even with a numeric value type.
lru.get("missing").toFixed();
// @ts-expect-error Peeking also preserves missing entries.
lru.peek("missing").toFixed();
// @ts-expect-error Writes must match the declared cache value type.
lru.set("one", "wrong");
// @ts-expect-error Cache reads retain the value type instead of returning any.
lru.get("one")?.toUpperCase();
const inferredCache = new LruCache(2, {
    onEvict(key: string, value: { id: number }) { value.id.toFixed(); },
});
inferredCache.set("record", { id: 1 });
// @ts-expect-error Eviction callback annotations also determine the stored value type.
inferredCache.set("record", { unrelated: true });
declare const names: ReturnType<typeof nameService.start>;
names.cache.get("res.partner\\0" + 1)?.resolve("Partner");
names.cache.get("missing")?.resolve(ERROR_INACCESSIBLE_OR_MISSING);
// @ts-expect-error Display name promises require a name or the inaccessible-record sentinel.
names.cache.get("missing")?.resolve(42);
// @ts-expect-error Display name promises cannot silently resolve undefined.
names.cache.get("missing")?.resolve();
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
    const checked = [file];
    for (const path of [
        "core/utils/collections/arrays.js",
        "core/utils/lru_cache.js",
        "core/utils/concurrency.js",
        "core/name_service.js",
        "core/domain.js",
        "core/py_js/py.js",
    ]) {
        const implementation = program.getSourceFile(resolve(webSource, path));
        assert.ok(implementation, path);
        checked.push(implementation);
    }
    const diagnostics = checked.flatMap((source) => [
        ...program.getSyntacticDiagnostics(source),
        ...program.getSemanticDiagnostics(source),
    ]);
    assert.deepEqual(
        diagnostics.map(
            (diagnostic) =>
                `${diagnostic.file.fileName}:${diagnostic.file.getLineAndCharacterOfPosition(diagnostic.start).line + 1}: ${ts.flattenDiagnosticMessageText(diagnostic.messageText, " ")}`,
        ),
        [],
    );
});
