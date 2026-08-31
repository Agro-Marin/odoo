// @ts-check

import { expect, test } from "@odoo/hoot";
import { Deferred } from "@web/core/utils/concurrency";
import { useAddInlineRecord, useX2ManyCrud } from "@web/fields/relational/x2many_crud";

/**
 * Neither export touches the component lifecycle -- despite the `use` prefix
 * they take their collaborators as arguments -- so they are exercised directly.
 * That is the point of testing them here: the branch each one takes is decided
 * by a single boolean, and a caller passing the wrong one gets a list that
 * silently deletes where it should unlink.
 *
 * @returns {{ list: any, calls: string[] }}
 */
function makeList() {
    /** @type {string[]} */
    const calls = [];
    const list = {
        addAndRemove: (/** @type {any} */ arg) => {
            calls.push(`addAndRemove:${JSON.stringify(arg)}`);
            return "addAndRemove";
        },
        linkTo: (/** @type {any} */ resId) => {
            calls.push(`linkTo:${resId}`);
            return "linkTo";
        },
        validateExtendedRecord: (/** @type {any} */ record) => {
            calls.push(`validate:${record.resId}`);
            return "validate";
        },
        forget: (/** @type {any} */ record) => {
            calls.push(`forget:${record.resId}`);
            return "forget";
        },
        delete: (/** @type {any} */ record) => {
            calls.push(`delete:${record.resId}`);
            return "delete";
        },
    };
    return { list, calls };
}

/**
 * @param {number} resId
 * @param {string[]} calls
 * @returns {any}
 */
function makeRecord(resId, calls) {
    return {
        resId,
        save: async (/** @type {any} */ options) => {
            calls.push(`save:${resId}:${JSON.stringify(options ?? null)}`);
        },
    };
}

test("many2many links through addAndRemove, one2many has no link at all", () => {
    const { list } = makeList();
    expect(typeof useX2ManyCrud(() => list, true).linkRecords).toBe("function");
    // The one2many branch leaves it undefined on purpose: there is nothing to
    // link to, and X2ManyField's `onSelected` calls it with `?.` for that reason.
    expect(useX2ManyCrud(() => list, false).linkRecords).toBe(undefined);
});

test("many2many linkRecords adds the ids without removing any", () => {
    const { list, calls } = makeList();
    const crud = useX2ManyCrud(() => list, true);
    crud.linkRecords([4, 7]);
    expect(calls).toEqual(['addAndRemove:{"add":[4,7]}']);
});

test("many2many saveAndLink saves without reloading, then links", async () => {
    const { list, calls } = makeList();
    const crud = useX2ManyCrud(() => list, true);
    await crud.saveAndLink(makeRecord(9, calls));
    // `reload: false` matters: the list is about to link the record itself, and
    // a reload here would be a second round trip for the same datapoint.
    expect(calls).toEqual(['save:9:{"reload":false}', "linkTo:9"]);
});

test("one2many saveAndLink validates in place and never saves the record", async () => {
    const { list, calls } = makeList();
    const crud = useX2ManyCrud(() => list, false);
    await crud.saveAndLink(makeRecord(9, calls));
    expect(calls).toEqual(["validate:9"]);
});

test("updateRecord saves first only for many2many", async () => {
    const m2m = makeList();
    await useX2ManyCrud(() => m2m.list, true).updateRecord(makeRecord(3, m2m.calls));
    expect(m2m.calls).toEqual(["save:3:null", "validate:3"]);

    const o2m = makeList();
    await useX2ManyCrud(() => o2m.list, false).updateRecord(makeRecord(3, o2m.calls));
    expect(o2m.calls).toEqual(["validate:3"]);
});

// The distinction that matters to the user: unlinking a many2many leaves the
// record alone, deleting a one2many child destroys it.
test("removeRecord forgets a many2many and deletes a one2many", () => {
    const m2m = makeList();
    useX2ManyCrud(() => m2m.list, true).removeRecord(makeRecord(5, m2m.calls));
    expect(m2m.calls).toEqual(["forget:5"]);

    const o2m = makeList();
    useX2ManyCrud(() => o2m.list, false).removeRecord(makeRecord(5, o2m.calls));
    expect(o2m.calls).toEqual(["delete:5"]);
});

test("the list is resolved per call, not captured once", () => {
    let current = makeList();
    const crud = useX2ManyCrud(() => current.list, true);
    crud.removeRecord(makeRecord(1, current.calls));
    const first = current;
    current = makeList();
    crud.removeRecord(makeRecord(2, current.calls));

    expect(first.calls).toEqual(["forget:1"]);
    expect(current.calls).toEqual(["forget:2"]);
});

test("addInlineRecord translates its arguments for addNew", async () => {
    /** @type {any[]} */
    const seen = [];
    const add = useAddInlineRecord({ addNew: async (params) => seen.push(params) });
    await add({ context: { a: 1 }, editable: "bottom" });
    expect(seen).toEqual([{ context: { a: 1 }, mode: "edit", position: "bottom" }]);
});

// The guard exists because "Add a line" is reachable twice before the first
// record materialises -- a double click, or a click plus the keyboard shortcut.
test("addInlineRecord ignores a second call while the first is in flight", async () => {
    const started = new Deferred();
    const release = new Deferred();
    let calls = 0;
    const add = useAddInlineRecord({
        addNew: async () => {
            calls++;
            started.resolve();
            await release;
        },
    });

    const first = add({ context: {}, editable: "bottom" });
    await started;
    await add({ context: {}, editable: "bottom" });
    expect(calls).toBe(1);

    release.resolve();
    await first;

    // ...and the guard is released, rather than wedging the button for good.
    await add({ context: {}, editable: "bottom" });
    expect(calls).toBe(2);
});

test("a failing addNew releases the guard", async () => {
    let calls = 0;
    const add = useAddInlineRecord({
        addNew: async () => {
            calls++;
            throw new Error("boom");
        },
    });

    await expect(add({ context: {}, editable: "bottom" })).rejects.toThrow("boom");
    await expect(add({ context: {}, editable: "bottom" })).rejects.toThrow("boom");
    expect(calls).toBe(2);
});
