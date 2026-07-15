import {
    click,
    contains,
    mailModels,
    openFormView,
    openKanbanView,
    openListView,
    start,
    startServer,
} from "@mail/../tests/mail_test_helpers";
import { ResPartner } from "@mail/../tests/mock_server/mock_models/res_partner";
import { describe, test } from "@odoo/hoot";
import { defineModels, fields, models } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");

class Stage extends models.Model {
    _name = "stage";
    name = fields.Char();
}
// Subclass — mutating the shared ResPartner._fields at module level would
// leak stage_id (and its "stage" relation) into every other suite's mock
// registry under the ESM loader.
class RottingResPartner extends ResPartner {
    stage_id = fields.Many2one({ relation: "stage" });
    is_rotting = fields.Boolean({ string: "Rotting" });
    rotting_days = fields.Integer({ string: "Days Rotting" });
    duration_tracking = fields.Json();
    grade = fields.Selection({
        selection: [
            ["good", "Good"],
            ["bad", "Bad"],
        ],
    });
}
defineModels({ ...mailModels, ResPartner: RottingResPartner, Stage });

const KANBAN_ARCH = `
    <kanban js_class="rotting_kanban">
        <progressbar field="grade" colors='{"good": "success", "bad": "danger"}'/>
        <field name="is_rotting"/>
        <templates>
            <t t-name="card">
                <field name="name"/>
                <field name="rotting_days" widget="rotting"/>
            </t>
        </templates>
    </kanban>`;

/** Two stages; "New" holds 2 rotting records out of 3, "Won" holds none. */
async function seedRottingRecords() {
    const pyEnv = await startServer();
    const [stageNewId, stageWonId] = pyEnv["stage"].create([
        { name: "New" },
        { name: "Won" },
    ]);
    pyEnv["res.partner"].create([
        {
            name: "Apple",
            stage_id: stageNewId,
            is_rotting: true,
            rotting_days: 5,
            grade: "good",
            duration_tracking: { [stageNewId]: 7 * 24 * 60 * 60 },
        },
        {
            name: "Banana",
            stage_id: stageNewId,
            is_rotting: false,
            rotting_days: 0,
            grade: "bad",
            duration_tracking: { [stageNewId]: 3 * 60 * 60 },
        },
        {
            name: "Cherry",
            stage_id: stageNewId,
            is_rotting: true,
            rotting_days: 12,
            grade: "good",
        },
        {
            name: "Durian",
            stage_id: stageWonId,
            is_rotting: false,
            rotting_days: 0,
            grade: "good",
        },
    ]);
    await start();
    return pyEnv;
}

test("kanban 'rotting' widget shows a day-count badge on rotting records only", async () => {
    await seedRottingRecords();
    await openKanbanView("res.partner", { arch: KANBAN_ARCH });
    await contains(".o_kanban_record .o_mail_resource_rotting_bg", { count: 2 });
    await contains(".o_kanban_record:contains('Apple') .o_mail_resource_rotting_bg", {
        text: "5d",
    });
    await contains(".o_kanban_record:contains('Cherry') .o_mail_resource_rotting_bg", {
        text: "12d",
    });
    await contains(".o_kanban_record:contains('Banana') .o_mail_resource_rotting_bg", {
        count: 0,
    });
});

test("kanban rotting badge title explains how long the record is stuck", async () => {
    await seedRottingRecords();
    await openKanbanView("res.partner", { arch: KANBAN_ARCH });
    await contains(
        ".o_kanban_record:contains('Apple') .o_mail_resource_rotting_bg[title='This record has been stuck in this stage for 5 days.']",
    );
});

test("rotting_kanban highlights rotting cards", async () => {
    await seedRottingRecords();
    await openKanbanView("res.partner", { arch: KANBAN_ARCH });
    await contains(".o_kanban_record.oe_kanban_card_rotting", { count: 2 });
    await contains(".o_kanban_record:contains('Banana'):not(.oe_kanban_card_rotting)");
});

// Grouping must be passed through the action context: mail's openKanbanView
// goes through action_service.doAction, and buildViewInfo overwrites the
// `groupBy` prop with `action.context.group_by` (action_info_builders.js).
// The domain keeps the mock env's preseeded base partners (admin, OdooBot,
// public user... all stage-less) out of the view — without it they form an
// extra "None" column at :eq(0).
const GROUPED_BY_STAGE = {
    context: { group_by: ["stage_id"] },
    domain: [["stage_id", "!=", false]],
};

test("grouped rotting_kanban shows a rotting counter pill only on columns with rotting records", async () => {
    await seedRottingRecords();
    await openKanbanView("res.partner", { arch: KANBAN_ARCH, ...GROUPED_BY_STAGE });
    await contains(".o_kanban_group", { count: 2 });
    await contains(".o_kanban_header .o_mail_resource_rotting_bg", { count: 1 });
    // "New" column: 2 of its 3 records are rotting; pill titled after the field
    await contains(
        ".o_kanban_group:eq(0) .o_kanban_header .o_mail_resource_rotting_bg[title='Rotting']",
        {
            text: "2",
        },
    );
    await contains(
        ".o_kanban_group:eq(1) .o_kanban_header .o_mail_resource_rotting_bg",
        {
            count: 0,
        },
    );
});

test("clicking the rotting counter pill filters the column down to rotting records", async () => {
    await seedRottingRecords();
    await openKanbanView("res.partner", { arch: KANBAN_ARCH, ...GROUPED_BY_STAGE });
    await contains(".o_kanban_group:eq(0) .o_kanban_record", { count: 3 });
    await click(".o_kanban_group:eq(0) .o_kanban_header .o_mail_resource_rotting_bg");
    await contains(".o_kanban_group:eq(0) .o_kanban_record", { count: 2 });
    await contains(".o_kanban_group.o_kanban_group_show_rotting", { count: 1 });
    await contains(".o_kanban_group:eq(0) .o_kanban_record:contains('Banana')", {
        count: 0,
    });
});

test("clicking the rotting counter pill again removes the filter", async () => {
    await seedRottingRecords();
    await openKanbanView("res.partner", { arch: KANBAN_ARCH, ...GROUPED_BY_STAGE });
    await click(".o_kanban_group:eq(0) .o_kanban_header .o_mail_resource_rotting_bg");
    await contains(".o_kanban_group:eq(0) .o_kanban_record", { count: 2 });
    await click(".o_kanban_group:eq(0) .o_kanban_header .o_mail_resource_rotting_bg");
    await contains(".o_kanban_group:eq(0) .o_kanban_record", { count: 3 });
    await contains(".o_kanban_group.o_kanban_group_show_rotting", { count: 0 });
});

test("list 'badge_rotting' widget appends a day-count badge to the m2o on rotting rows", async () => {
    await seedRottingRecords();
    await openListView("res.partner", {
        arch: `
            <list>
                <field name="name"/>
                <field name="is_rotting" column_invisible="1"/>
                <field name="rotting_days" column_invisible="1"/>
                <field name="stage_id" widget="badge_rotting"/>
            </list>`,
    });
    await contains(".o_data_row .o_mail_resource_rotting_bg", { count: 2 });
    await contains(".o_data_row:contains('Apple') .o_mail_resource_rotting_bg", {
        text: "5d",
    });
    await contains(".o_data_row:contains('Apple')", { text: "New" });
    await contains(".o_data_row:contains('Banana') .o_mail_resource_rotting_bg", {
        count: 0,
    });
});

test("form 'rotting_statusbar_duration' swaps the stage duration for a rot badge when rotting", async () => {
    const pyEnv = await seedRottingRecords();
    const [rottenId] = pyEnv["res.partner"].search([["name", "=", "Apple"]]);
    await openFormView("res.partner", rottenId, {
        arch: `
            <form>
                <field name="is_rotting" invisible="1"/>
                <field name="rotting_days" invisible="1"/>
                <field name="stage_id" widget="rotting_statusbar_duration"/>
            </form>`,
    });
    await contains(
        ".o_statusbar_status button:contains('New') .o_mail_resource_rotting_bg",
        {
            text: "5d",
        },
    );
    // the regular time-in-stage counter is hidden on the rotting selected stage
    await contains(".o_statusbar_status span[title='7 days']", { count: 0 });
});

test("form 'rotting_statusbar_duration' keeps the stage duration on non-rotting records", async () => {
    const pyEnv = await seedRottingRecords();
    const [freshId] = pyEnv["res.partner"].search([["name", "=", "Banana"]]);
    await openFormView("res.partner", freshId, {
        arch: `
            <form>
                <field name="is_rotting" invisible="1"/>
                <field name="rotting_days" invisible="1"/>
                <field name="stage_id" widget="rotting_statusbar_duration"/>
            </form>`,
    });
    await contains(".o_statusbar_status button:contains('New') span[title='3 hours']");
    await contains(".o_statusbar_status .o_mail_resource_rotting_bg", { count: 0 });
});
