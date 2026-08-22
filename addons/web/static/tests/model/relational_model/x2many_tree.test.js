// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    allX2manyLists,
    buildCommitSpec,
    collectPendingCommands,
    commitSubtree,
    x2manyLists,
} from "@web/model/relational_model/x2many_tree";

describe.current.tags("headless");

/**
 * @param {Record<string, any>} lists
 * @param {Record<string, any>} [fieldOverrides]
 * @returns {any}
 */
function makeRecord(lists, fieldOverrides = {}) {
    /** @type {Record<string, any>} */
    const activeFields = {};
    /** @type {Record<string, any>} */
    const fields = {};
    /** @type {Record<string, any>} */
    const data = {};
    for (const [name, list] of Object.entries(lists)) {
        activeFields[name] = {};
        fields[name] = { name, type: "one2many", ...(fieldOverrides[name] || {}) };
        data[name] = list;
    }
    activeFields.name = {};
    fields.name = { name: "name", type: "char" };
    data.name = "x";
    return /** @type {any} */ ({ activeFields, fields, data });
}

/**
 * @param {Partial<any>} [props]
 * @returns {any}
 */
function makeList({ pending = null, staged = false, cached = [] } = {}) {
    /** @type {boolean[]} */
    const cleared = [];
    /** @type {any[]} */
    const committed = [];
    return {
        pendingCommands: pending,
        hasStagedCommands: staged,
        cachedRecords: cached,
        getCachedRecord: (/** @type {string} */ id) =>
            cached.find((/** @type {any} */ r) => r.__id === id),
        _clearCommands: () => cleared.push(true),
        _commitSave: (/** @type {any} */ v) => committed.push(v),
        cleared,
        committed,
    };
}

describe("which lists each selector yields", () => {
    test("x2manyLists skips a property-backed list, allX2manyLists does not", () => {
        const own = makeList();
        const prop = makeList();
        const record = makeRecord(
            { lines: own, "properties.rel": prop },
            { "properties.rel": { relatedPropertyField: { name: "properties" } } },
        );

        expect([...x2manyLists(record)].map(([n]) => n)).toEqual(["lines"]);
        expect([...allX2manyLists(record)].map(([n]) => n)).toEqual([
            "lines",
            "properties.rel",
        ]);
    });

    test("a falsy list is skipped rather than yielded", () => {
        const record = makeRecord({ lines: null, others: makeList() });
        expect([...allX2manyLists(record)].map(([n]) => n)).toEqual(["others"]);
    });
});

describe("collectPendingCommands", () => {
    test("includes property lists — replay is staged on them too", () => {
        const p = Promise.resolve();
        const record = makeRecord(
            { "properties.rel": makeList({ pending: p }) },
            { "properties.rel": { relatedPropertyField: { name: "properties" } } },
        );
        expect(collectPendingCommands(record)).toEqual([p]);
    });

    test("descends into cached sub-records", () => {
        const deep = Promise.resolve();
        const child = makeRecord({ sub: makeList({ pending: deep }) });
        const record = makeRecord({ lines: makeList({ cached: [child] }) });
        expect(collectPendingCommands(record)).toEqual([deep]);
    });

    test("a cycle terminates instead of recursing forever", () => {
        const list = makeList();
        const record = makeRecord({ lines: list });
        list.cachedRecords = [record];
        expect(collectPendingCommands(record)).toEqual([]);
    });

    test("lists with nothing in flight contribute nothing", () => {
        const record = makeRecord({ lines: makeList() });
        expect(collectPendingCommands(record)).toEqual([]);
    });
});

describe("buildCommitSpec", () => {
    test("names only the fields that have staged work", () => {
        const record = makeRecord({
            dirty: makeList({ staged: true }),
            clean: makeList(),
        });
        expect(buildCommitSpec(record)).toEqual({ dirty: {} });
    });

    test("a clean list whose child is dirty is still named, nested", () => {
        const child = makeRecord({ sub: makeList({ staged: true }) });
        const record = makeRecord({ lines: makeList({ cached: [child] }) });
        expect(buildCommitSpec(record)).toEqual({ lines: { fields: { sub: {} } } });
    });

    test("a property list is never specified, even when staged", () => {
        const record = makeRecord(
            { "properties.rel": makeList({ staged: true }) },
            { "properties.rel": { relatedPropertyField: { name: "properties" } } },
        );
        expect(buildCommitSpec(record)).toEqual({});
    });
});

describe("commitSubtree", () => {
    test("a field the server did not report has its staged commands dropped", () => {
        const list = makeList({ staged: true });
        const record = makeRecord({ lines: list });
        commitSubtree(record, {});
        expect(list.cleared.length).toBe(1);
        expect(list.committed.length).toBe(0);
    });

    test("a reported field is committed with the server value", () => {
        const list = makeList();
        const record = makeRecord({ lines: list });
        commitSubtree(record, { lines: [1, 2] });
        expect(list.committed).toEqual([[1, 2]]);
        expect(list.cleared.length).toBe(0);
    });

    test("nested rows are committed through their cached datapoint", () => {
        const inner = makeList();
        const child = makeRecord({ sub: inner });
        child.__id = 7;
        const outer = makeList({ cached: [child] });
        const record = makeRecord({ lines: outer });
        commitSubtree(record, { lines: [{ id: 7, sub: [42] }] });
        expect(inner.committed).toEqual([[42]]);
    });

    test("a cycle commits each record once", () => {
        const list = makeList();
        const record = makeRecord({ lines: list });
        record.__id = 1;
        list.cachedRecords = [record];
        list.getCachedRecord = () => record;
        commitSubtree(record, { lines: [{ id: 1, lines: [9] }] });
        expect(list.committed.length).toBe(1);
    });
});
