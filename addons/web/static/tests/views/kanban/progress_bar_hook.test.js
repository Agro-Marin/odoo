// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { Deferred, runAllTimers, tick } from "@odoo/hoot-mock";
import { Component, xml } from "@odoo/owl";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import { useProgressBar } from "@web/views/kanban/progress_bar_hook";

describe.current.tags("desktop");

const COLORS = { done: "success", blocked: "danger" };

/**
 * @param {Object} [opts]
 */
function makeGroup({ id = "g1", value = "a", count = 3, records = [] } = {}) {
    return {
        id,
        value,
        serverValue: value,
        count,
        aggregates: {},
        groupDomain: [["stage", "=", value]],
        list: { count: records.length || count, records },
    };
}

/**
 * @param {Object} [opts]
 */
function makeModel({ groups = [makeGroup()], readProgressBar } = {}) {
    /** @type {Record<string, Function[]>} */
    const hooks = {};
    const calls = [];
    return {
        calls,
        isReady: true,
        root: {
            groups,
            groupByField: { name: "stage" },
            fields: { state: {} },
            context: {},
            domain: [],
            groupBy: ["stage"],
            resModel: "task",
        },
        orm: {
            call: (resModel, method, args, kwargs) => {
                calls.push(method);
                return readProgressBar
                    ? readProgressBar(kwargs)
                    : Promise.resolve({ a: { done: 2, blocked: 0 } });
            },
            formattedReadGroup: () => Promise.resolve([]),
        },
        subscribeLifecycle(name, cb) {
            (hooks[name] ||= []).push(cb);
            return () => {};
        },
        async fire(name, ...args) {
            for (const cb of hooks[name] || []) {
                await cb(...args);
            }
        },
    };
}

/**
 * @param {Object} [opts]
 */
async function mountProgressBar({
    model = makeModel(),
    aggregateFields = [],
    activeBars = {},
} = {}) {
    /** @type {any} */
    let state = null;
    class Host extends Component {
        static template = xml`<div/>`;
        static props = {};
        setup() {
            state = useProgressBar(
                { fieldName: "state", colors: COLORS, help: "" },
                model,
                aggregateFields,
                activeBars,
            );
        }
    }
    await mountWithCleanup(Host);
    return { state, model };
}

async function load(model) {
    await model.fire("onWillLoadRoot", {
        context: {},
        domain: [],
        groupBy: ["stage"],
        resModel: "task",
    });
    await model.fire("onRootLoaded");
}

describe("seeding a group from the fetched counts", () => {
    test("bars come from the colors, plus an Other bar that absorbs the remainder", async () => {
        const model = makeModel({ groups: [makeGroup({ count: 5 })] });
        const { state } = await mountProgressBar({ model });
        await load(model);

        const info = state.getGroupInfo(model.root.groups[0]);
        expect(info.bars.map((b) => b.value.toString())).toEqual([
            "done",
            "blocked",
            "Symbol(False)",
        ]);
        expect(info.bars.map((b) => b.count)).toEqual([2, 0, 3], {
            message: "Other is group.count minus the coloured counts",
        });
        expect(info.total).toBe(5);
        expect(info.isReady).toBe(true);
    });

    test("a group the fetch says nothing about seeds every bar at zero", async () => {
        const model = makeModel({
            groups: [makeGroup({ id: "g2", value: "z", count: 4 })],
        });
        const { state } = await mountProgressBar({ model });
        await load(model);

        const info = state.getGroupInfo(model.root.groups[0]);
        expect(info.bars.map((b) => b.count)).toEqual([0, 0, 4]);
        expect(info.total).toBe(4);
    });
});

describe("the epoch guard on the counts fetch", () => {
    test("a superseded response is discarded, and the last one wins", async () => {
        const first = new Deferred();
        const second = new Deferred();
        const pending = [first, second];
        const model = makeModel({
            groups: [makeGroup({ count: 5 })],
            readProgressBar: () => pending.shift() ?? Promise.resolve({}),
        });
        const { state } = await mountProgressBar({ model });
        pending.unshift(
            /** @type {any} */ (Promise.resolve({ a: { done: 2, blocked: 0 } })),
        );
        await load(model);

        state.updateCounts(model.root.groups[0], null);
        state.updateCounts(model.root.groups[0], null);

        second.resolve({ a: { done: 4, blocked: 1 } });
        await tick();
        await tick();
        first.resolve({ a: { done: 99, blocked: 99 } });
        await tick();
        await tick();
        await runAllTimers();

        const info = state.getGroupInfo(model.root.groups[0]);
        expect(info.bars.map((b) => b.count)).toEqual([4, 1, 0], {
            message: "the stale response never landed",
        });
    });
});

describe("group membership changing under a fetch", () => {
    test("counts are not applied when the groups changed, and a retry is scheduled", async () => {
        const groups = [makeGroup({ id: "g1", count: 5 })];
        const answer = new Deferred();
        const model = makeModel({
            groups,
            readProgressBar: () => answer,
        });
        const { state } = await mountProgressBar({ model });
        answer.resolve({ a: { done: 2, blocked: 0 } });
        await load(model);
        const before = state.getGroupInfo(groups[0]).bars.map((b) => b.count);

        const late = new Deferred();
        model.orm.call = () => {
            model.calls.push("read_progress_bar");
            return late;
        };
        state.updateCounts(groups[0], null);
        groups.push(makeGroup({ id: "g2", value: "b", count: 1 }));
        late.resolve({ a: { done: 99, blocked: 99 }, b: { done: 1, blocked: 0 } });
        await tick();
        await tick();

        expect(state.getGroupInfo(groups[0]).bars.map((b) => b.count)).toEqual(before, {
            message:
                "the answer described a different set of groups, so it was dropped",
        });

        const callsBefore = model.calls.length;
        await runAllTimers();
        expect(model.calls.length > callsBefore).toBe(true, {
            message: "and the retry the guard scheduled did fire",
        });
    });
});

describe("optimistic accounting for a record move", () => {
    /** @returns {Promise<any>} */
    async function twoGroups() {
        const record = { id: "r1", data: { state: "done" } };
        const source = makeGroup({ id: "g1", value: "a", count: 3, records: [record] });
        const target = makeGroup({ id: "g2", value: "b", count: 1 });
        const model = makeModel({
            groups: [source, target],
            readProgressBar: () =>
                Promise.resolve({
                    a: { done: 2, blocked: 0 },
                    b: { done: 0, blocked: 1 },
                }),
        });
        const { state } = await mountProgressBar({ model });
        await load(model);
        return { state, model, source, target, record };
    }

    test("a registered move shifts one unit from source to target without refetching", async () => {
        const { state, model, source, target, record } = await twoGroups();
        const callsBefore = model.calls.length;

        state.registerRecordMove("r1", "g1", "g2");
        state.updateCounts(target, record);

        expect(state.getGroupInfo(source).bars[0].count).toBe(1, {
            message: "source lost the unit it held for that value",
        });
        expect(state.getGroupInfo(target).bars[0].count).toBe(1, {
            message: "target gained it",
        });
        expect(model.calls.length).toBe(callsBefore, {
            message: "and nothing was refetched to learn that",
        });
    });

    test("the reconcile fetch follows, once, after the debounce", async () => {
        const { state, model, target, record } = await twoGroups();
        const callsBefore = model.calls.length;

        state.registerRecordMove("r1", "g1", "g2");
        state.updateCounts(target, record);
        expect(model.calls.length).toBe(callsBefore);

        await runAllTimers();
        expect(model.calls.length).toBe(callsBefore + 1, {
            message:
                "the optimistic delta is confirmed against the server exactly once",
        });
    });

    test("registering the same record twice keeps the first move", async () => {
        const { state, source, target, record } = await twoGroups();

        state.registerRecordMove("r1", "g1", "g2");
        state.registerRecordMove("r1", "g2", "g1");
        state.updateCounts(target, record);

        expect(state.getGroupInfo(source).bars[0].count).toBe(1);
        expect(state.getGroupInfo(target).bars[0].count).toBe(1);
    });

    test("a cancelled move takes the ordinary refetch path instead", async () => {
        const { state, model, source, target, record } = await twoGroups();
        const callsBefore = model.calls.length;

        state.registerRecordMove("r1", "g1", "g2");
        state.cancelRecordMove("r1");
        state.updateCounts(target, record);

        expect(state.getGroupInfo(source).bars[0].count).toBe(2, {
            message: "no optimistic delta was applied",
        });
        expect(model.calls.length).toBe(callsBefore + 1, {
            message: "the counts were refetched instead",
        });
    });

    test("a move on the field the view is grouped by is left to the refetch", async () => {
        const { state, model, source, target, record } = await twoGroups();
        model.root.groupByField = { name: "state" };
        const callsBefore = model.calls.length;

        state.registerRecordMove("r1", "g1", "g2");
        state.updateCounts(target, record);

        expect(state.getGroupInfo(source).bars[0].count).toBe(2);
        expect(model.calls.length).toBe(callsBefore + 1);
    });
});
