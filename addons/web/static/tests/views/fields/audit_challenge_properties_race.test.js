// @ts-check

/**
 * AUDIT CHALLENGE — properties mutations are whole-array writes built from a
 * snapshot taken BEFORE the previous write has applied.
 *
 * Every handler derives its outgoing array from `propertiesList`, which reads
 * `record.data[name]` at call time, and then hands the whole array to
 * `_updateRecordProperties` -> `record.update`. `record.update` defers into
 * `model.mutex`, so `record.data` is NOT updated synchronously. Most call sites
 * do not await (`onPropertyValueChange`, `onGroupMoveTo`, `onPropertyDelete`,
 * `_setDefaultPropertyValue`, `onPropertyMoveTo`'s tail).
 *
 * So two mutations issued before the first has applied both snapshot the same
 * stale array: the second write wins wholesale and the first change is silently
 * lost — no error, no conflict.
 *
 * The hazard is already acknowledged in-tree: `onPropertyMoveTo` unfolds
 * separators "directly on the local copy" precisely because "`_toggleSeparators`
 * would re-read the record data, which doesn't contain the spliced separators
 * yet". That is a local workaround for this general defect.
 *
 * Delegation-pattern mock over the real PropertiesField.prototype, with an
 * `update` that applies asynchronously the way the model mutex does.
 */

import { describe, expect, test } from "@odoo/hoot";
import { PropertiesField } from "@web/fields/specialized/properties/properties_field";

describe.current.tags("headless");

/**
 * @param {any[]} properties
 */
function makeField(properties) {
    const record = {
        data: { properties },
        /** serialises writes and applies them asynchronously, like model.mutex */
        _queue: Promise.resolve(),
        update(changes) {
            record._queue = record._queue.then(async () => {
                await Promise.resolve();
                Object.assign(record.data, changes);
            });
            return record._queue;
        },
    };
    const field = Object.create(PropertiesField.prototype);
    field.props = { record, name: "properties" };
    return { field, record };
}

const PROPERTIES = [
    { name: "sep", type: "separator", string: "Section", value: false },
    { name: "a", type: "char", string: "A", value: false },
];

describe("concurrent properties mutations", () => {
    test("a value edit survives a fold issued before it applied", async () => {
        const { field, record } = makeField(PROPERTIES.map((p) => ({ ...p })));

        // The user types into a property, then folds a group before that write
        // has applied. Both mutations are issued in the same tick.
        const edit = field.onPropertyValueChange("a", "Acme");
        const fold = field._toggleSeparators(["sep"]);
        await Promise.all([edit, fold]);

        const saved = record.data.properties;
        expect(saved.find((p) => p.name === "sep").value).toBe(true);
        // Pre-fix `false`: the fold snapshotted the list before the edit landed
        // and its whole-array write reverted it.
        expect(saved.find((p) => p.name === "a").value).toBe("Acme");
    });

    test("a fold survives a value edit issued before it applied", async () => {
        const { field, record } = makeField(PROPERTIES.map((p) => ({ ...p })));

        // Same collision, opposite order.
        const fold = field._toggleSeparators(["sep"]);
        const edit = field.onPropertyValueChange("a", "Acme");
        await Promise.all([fold, edit]);

        const saved = record.data.properties;
        expect(saved.find((p) => p.name === "a").value).toBe("Acme");
        expect(saved.find((p) => p.name === "sep").value).toBe(true);
    });

    test("mutations awaited one at a time both survive (control)", async () => {
        const { field, record } = makeField(PROPERTIES.map((p) => ({ ...p })));

        // Sequential, fully awaited: never raced even before the fix. This is
        // the control isolating the defect to mutations issued concurrently.
        await field.onPropertyValueChange("a", "Acme");
        await field._toggleSeparators(["sep"]);

        const saved = record.data.properties;
        expect(saved.find((p) => p.name === "a").value).toBe("Acme");
        expect(saved.find((p) => p.name === "sep").value).toBe(true);
    });

    test("harness sanity: the mock defers writes like model.mutex", async () => {
        // Exercises the MOCK alone, not the component, so it holds before and
        // after the fix. The race tests above are only meaningful if
        // `record.update` really is asynchronous — if this ever fails, they are
        // artefacts of the harness rather than statements about the component.
        const { record } = makeField(PROPERTIES.map((p) => ({ ...p })));

        record.update({ properties: [{ name: "x", value: 1 }] });
        // Not applied synchronously: this is what makes a caller's pre-read
        // snapshot go stale.
        expect(record.data.properties.find((p) => p.name === "x")).toBe(undefined);

        await record._queue;
        expect(record.data.properties.map((p) => p.name)).toEqual(["x"]);
    });

    test("mutation handlers return an awaitable promise", async () => {
        // Callers could not sequence these mutations even when they wanted to:
        // the handlers issued the update and returned undefined.
        const { field } = makeField(PROPERTIES.map((p) => ({ ...p })));
        expect(field.onPropertyValueChange("a", "Acme")).toBeInstanceOf(Promise);
        expect(field._toggleSeparators(["sep"])).toBeInstanceOf(Promise);
    });
});
