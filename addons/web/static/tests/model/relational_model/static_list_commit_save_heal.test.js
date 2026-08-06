// @ts-check

/**
 * Regression tests for ``StaticList._commitSave`` when the server's post-save id
 * list cannot be reconciled with the client's staged CREATEs.
 *
 * ``_commitSave`` maps the nth CREATE onto the nth new resId in ascending order.
 * When the counts disagree — a ``create()`` override or a compute inserted rows
 * of its own, which is the everyday shape for an invoice's tax and balancing
 * lines — that mapping is untrustworthy, so no id is remapped. But membership is
 * still adopted from the server, because it is the only true account of the
 * relation. That left ``_currentIds`` naming ids no datapoint backed:
 * ``_materializeWindow`` drops those, so
 *
 *   - the row the user had just created VANISHED from the page (and its
 *     datapoint was evicted by ``_pruneCache``),
 *   - the rows the server added never appeared,
 *   - while ``count`` went on reporting all of them.
 *
 * Reproduced end-to-end through ``record.save({reload: false})`` on a mounted
 * form: 6 rendered rows before the save, 5 after, ``count`` 7.
 *
 * ``_healMissingWindow`` reads the unbacked window ids instead of hiding them.
 * The load is tracked on ``_commandsPromise`` (``_commitSave`` is synchronous,
 * called mid-``record_save.save``), which is also what makes a later save
 * sequence behind it via ``waitForPendingCommands``.
 */

import { describe, expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-dom";
import {
    defineModels,
    fields,
    models,
    mountView,
    onRpc,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { makeActiveField } from "@web/model/relational_model/field_metadata";
import { RelationalRecord } from "@web/model/relational_model/record";
import { RelationalModel } from "@web/model/relational_model/relational_model";
import { StaticList } from "@web/model/relational_model/static_list";

describe.current.tags("desktop");

class Partner extends models.Model {
    name = fields.Char();
    turtles = fields.One2many({ relation: "turtle", relation_field: "turtle_trululu" });
    _records = [{ id: 1, name: "first", turtles: [2, 3] }];
}

class Turtle extends models.Model {
    name = fields.Char();
    turtle_trululu = fields.Many2one({ relation: "partner" });
    _records = [2, 3, 90, 91, 999].map((id) => ({ id, name: `t${id}` }));
}

defineModels([Partner, Turtle]);

const ARCH = `
    <form>
        <field name="name"/>
        <field name="turtles">
            <list><field name="name"/></list>
        </field>
    </form>`;

/** Capture the model instance the view builds. */
function captureModel() {
    const box = {};
    patchWithCleanup(RelationalModel.prototype, {
        setup() {
            super.setup(...arguments);
            box.model = this;
        },
    });
    return box;
}

async function settle() {
    await animationFrame();
    await animationFrame();
}

describe("a save whose server ids outnumber the staged CREATEs", () => {
    /**
     * @param {number[]} serverTurtles post-save value the server reports
     * @returns {Promise<{ list: any, rpcCount: number }>}
     */
    async function saveWith(serverTurtles) {
        const box = captureModel();
        let readCount = 0;
        onRpc("turtle", "web_read", () => {
            readCount++;
        });
        onRpc("partner", "web_save", () => [{ id: 1, turtles: serverTurtles }]);
        await mountView({ type: "form", resModel: "partner", resId: 1, arch: ARCH });
        const record = box.model.root;
        const list = record.data.turtles;
        await record.update({ turtles: [[0, false, { name: "user line" }]] });
        await settle();
        expect(list.records.length).toBe(3);
        readCount = 0;
        await record.save({ reload: false });
        await list._commandsPromise;
        await settle();
        return { list, rpcCount: readCount };
    }

    test("the created row and the server's own rows are all rendered", async () => {
        const { list } = await saveWith([2, 3, 90, 91]);

        expect(list.count).toBe(4);
        expect(list._currentIds).toEqual([2, 3, 90, 91]);
        // every member is backed by a datapoint: nothing silently dropped
        expect(list.records.length).toBe(4);
        expect(list.records.map((r) => r.resId)).toEqual([2, 3, 90, 91]);
        expect(list.records.map((r) => r.data.name)).toEqual([
            "t2",
            "t3",
            "t90",
            "t91",
        ]);
    });

    test("count and rendered rows agree", async () => {
        const { list } = await saveWith([2, 3, 90, 91]);
        expect(list.records.length).toBe(list.count);
    });

    test("no virtual id survives in membership or cache", async () => {
        const { list } = await saveWith([2, 3, 90, 91]);
        expect(list._currentIds.every((id) => typeof id === "number")).toBe(true);
        expect(Object.keys(list._cache).sort()).toEqual(["2", "3", "90", "91"]);
    });

    test("the matching case still costs no extra read", async () => {
        // counts agree -> the virtual id is remapped, every member is cached
        const { list, rpcCount } = await saveWith([2, 3, 90]);
        expect(list.records.length).toBe(3);
        expect(list._currentIds).toEqual([2, 3, 90]);
        expect(rpcCount).toBe(0);
    });
});

describe("a save whose new id is not where the created row was", () => {
    test("the pairing is refused: no rekey, the foreign row is loaded fresh", async () => {
        // Counts agree — one CREATE, one new id — but the server dropped our
        // row and inserted 999 of its own, at a different position. The old
        // rank-order zip grafted our edited datapoint onto resId 999, so every
        // later update wrote to a row we never created.
        const box = captureModel();
        onRpc("partner", "web_save", () => [{ id: 1, turtles: [2, 999, 3] }]);
        await mountView({ type: "form", resModel: "partner", resId: 1, arch: ARCH });
        const record = box.model.root;
        const list = record.data.turtles;
        await record.update({ turtles: [[0, false, { name: "user line" }]] });
        await settle();
        const virtualId = list.records.at(-1)._virtualId;
        expect(virtualId).not.toBe(false);

        await record.save({ reload: false });
        await list._commandsPromise;
        await settle();

        // membership adopted from the server, nothing grafted
        expect(list._currentIds).toEqual([2, 3, 999]);
        expect(list._currentIds.every((id) => typeof id === "number")).toBe(true);
        expect(virtualId in list._cache).toBe(false);
        // the foreign row shows the SERVER's data, not our edited datapoint
        const foreign = list._cache[999];
        expect(foreign.data.name).toBe("t999");
        expect(foreign._virtualId).toBe(false);
        expect(list.records.map((r) => r.data.name)).toEqual(["t2", "t3", "t999"]);
    });
});

describe("_healMissingWindow in isolation", () => {
    function makeList({ resIds = [], limit = 5 } = {}) {
        const loaded = [];
        const rows = {};
        for (const id of [1, 2, 3, 4, 5]) {
            rows[id] = { id, display_name: `Rec ${id}` };
        }
        const model = {
            Class: { Record: RelationalRecord, StaticList },
            _patchConfig: (config, patch) => Object.assign(config, patch),
            _loadRecords: async ({ resIds: ids }) => {
                loaded.push([...ids]);
                return ids.map((id) => rows[id]);
            },
        };
        const config = {
            resModel: "res.partner",
            activeFields: { display_name: makeActiveField() },
            fields: { display_name: { type: "char", name: "display_name" } },
            relationField: false,
            offset: 0,
            limit,
            resIds,
            orderBy: [],
            context: {},
        };
        const parent = {
            evalContext: {},
            evalContextWithVirtualIds: {},
            _isEvalContextReady: true,
        };
        const list = new StaticList(
            model,
            config,
            resIds.map((id) => rows[id]),
            { parent, onUpdate: async () => {} },
        );
        return { list, loaded };
    }

    test("reads only the window ids that have no datapoint", async () => {
        const { list, loaded } = makeList({ resIds: [1, 2], limit: 5 });
        list._currentIds = [1, 2, 3, 4];

        list._healMissingWindow();
        await list._commandsPromise;

        expect(loaded).toEqual([[3, 4]]);
        expect(list.records.map((r) => r.resId)).toEqual([1, 2, 3, 4]);
    });

    test("issues no read when every member is already backed", async () => {
        const { list, loaded } = makeList({ resIds: [1, 2], limit: 5 });
        list._healMissingWindow();
        expect(loaded).toEqual([]);
        expect(list._commandsPromise).toBe(null);
    });

    test("stays within the page window", async () => {
        const { list, loaded } = makeList({ resIds: [1], limit: 2 });
        list._currentIds = [1, 3, 4, 5];

        list._healMissingWindow();
        await list._commandsPromise;

        // only id 3 is on the current page; 4 and 5 wait for pagination
        expect(loaded).toEqual([[3]]);
    });
});
