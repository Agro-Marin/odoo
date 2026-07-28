// @ts-check

/**
 * Regression tests for the missing x2many commit step on the ``reload: false``
 * save path.
 *
 * That path keeps the record datapoint alive and editable — ``form_controller``,
 * ``form_view_dialog``, ``x2many_crud``, the kanban quick-create and a handful
 * of enterprise callers all use it — but it used to leave every relation
 * describing the PRE-save world:
 *
 *   1. the post-save clean-up walked ``record._changes``, so a list the user
 *      had not staged an edit into was never visited at all — and a list seeded
 *      by the creation onchange lives in ``_values``, so the one list that most
 *      needed re-baselining was precisely the one skipped;
 *   2. even where it did run, ``_clearCommands`` only drops the pending log: the
 *      list never learned the ids the write had just assigned, so
 *      ``config.resIds`` stayed empty and the rows kept their virtual ids.
 *
 * The visible consequence: editing a row that the save had just persisted
 * staged a CREATE instead of an UPDATE, so the following save wrote a SECOND
 * row. A rename became a duplicate.
 *
 * The fix asks ``web_save`` for the relation's post-save id list (a bare ``{}``
 * sub-spec, which ``web_read`` answers with the raw ids) and hands it to
 * ``StaticList._commitSave``.
 */

import { describe, expect, test } from "@odoo/hoot";
import {
    Command,
    defineModels,
    fields,
    models,
    mountView,
    onRpc,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { RelationalModel } from "@web/model/relational_model/relational_model";

describe.current.tags("desktop");

class Partner extends models.Model {
    name = fields.Char();
    turtles = fields.One2many({ relation: "turtle", relation_field: "turtle_trululu" });
    _records = [{ id: 1, name: "first", turtles: [2] }];
}

class Turtle extends models.Model {
    name = fields.Char();
    turtle_trululu = fields.Many2one({ relation: "partner" });
    _records = [{ id: 2, name: "t2" }];
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

/** Seed every new record with one onchange-created line. */
function seedLineOnCreate() {
    patchWithCleanup(Partner.prototype, {
        onchange() {
            const res = super.onchange(...arguments);
            res.value = res.value || {};
            res.value.turtles = [Command.create({ name: "auto line" })];
            return res;
        },
    });
}

describe("reload:false save re-baselines its x2many lists", () => {
    test("editing a just-saved line writes an UPDATE, not a second CREATE", async () => {
        const box = captureModel();
        seedLineOnCreate();
        const saves = [];
        onRpc("partner", "web_save", ({ args }) => {
            saves.push(JSON.parse(JSON.stringify(args[1])));
        });
        await mountView({ type: "form", resModel: "partner", arch: ARCH });

        const record = box.model.root;
        const list = record.data.turtles;
        expect(list._commands.length).toBe(1);

        await record.update({ name: "hello" });
        await record.save({ reload: false });

        // The list has adopted the write: the seeded row now carries a real id.
        expect(list._commands).toEqual([]);
        expect(list._initialCommands).toEqual([]);
        expect(list.config.resIds.length).toBe(1);
        const line = list.records[0];
        expect(typeof line.resId).toBe("number");
        expect(line._virtualId).toBe(false);
        expect(list._currentIds).toEqual([line.resId]);

        await line.update({ name: "renamed" });
        await record.save({ reload: false });

        expect(saves.length).toBe(2);
        const commands = saves[1].turtles;
        expect(commands.length).toBe(1);
        expect(commands[0][0]).toBe(1); // 1 = UPDATE, not 0 = CREATE
        expect(commands[0][1]).toBe(line.resId);
        expect(commands[0][2]).toEqual({ name: "renamed" });
    });

    test("a discard after the save does not resurrect the seeded row", async () => {
        const box = captureModel();
        seedLineOnCreate();
        await mountView({ type: "form", resModel: "partner", arch: ARCH });

        const record = box.model.root;
        const list = record.data.turtles;
        await record.update({ name: "hello" });
        await record.save({ reload: false });
        const savedIds = [...list._currentIds];

        await record.update({ name: "hello again" });
        await record.discard();
        await list._commandsPromise;

        expect(list._currentIds).toEqual(savedIds);
        expect(list._commands).toEqual([]);
        expect(list.records.length).toBe(1);
    });

    test("a save touching no relation still sends an empty specification", async () => {
        const box = captureModel();
        const specs = [];
        onRpc("partner", "web_save", ({ kwargs }) => {
            specs.push(kwargs.specification);
        });
        await mountView({
            type: "form",
            resModel: "partner",
            resId: 1,
            arch: ARCH,
        });

        await box.model.root.update({ name: "renamed" });
        await box.model.root.save({ reload: false });

        expect(specs).toEqual([{}]);
    });
});
