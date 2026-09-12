import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import {
    contains,
    defineModels,
    fields,
    mockService,
    models,
    mountView,
    onRpc,
} from "@web/../tests/web_test_helpers";

class EventEvent extends models.Model {
    _name = "event.event";
    name = fields.Char();
    _records = [{ id: 1, name: "Conference" }];
}

class EventRegistration extends models.Model {
    _name = "event.registration";
    name = fields.Char();
    barcode = fields.Char();
    event_id = fields.Many2one({ relation: "event.event" });
    _records = [{ id: 1, name: "Ada", barcode: "B1", event_id: 1 }];
}

defineMailModels();
defineModels({ EventEvent, EventRegistration });

describe.current.tags("desktop");

const ARCHES = {
    kanban: `
        <kanban js_class="registration_summary_dialog_kanban">
            <templates>
                <t t-name="card">
                    <field name="name"/>
                    <field name="barcode"/>
                    <field name="event_id"/>
                </t>
            </templates>
        </kanban>`,
    list: `
        <list js_class="registration_summary_dialog_list">
            <field name="name"/>
            <field name="barcode"/>
            <field name="event_id"/>
        </list>`,
};

for (const type of ["kanban", "list"]) {
    test(`registration desk ${type}: dismissing the summary dialog reloads the view`, async () => {
        // the dialog is dismissed by Escape or a click outside: only the
        // dialog service's onClose runs, none of the dialog's own buttons
        mockService("dialog", {
            add(component, props, options) {
                expect.step(`dialog ${Object.keys(props).join(",")}`);
                options.onClose();
                return () => {};
            },
        });
        onRpc("event.registration", "register_attendee", () => ({ id: 1 }));
        onRpc("event.registration", "web_search_read", () =>
            expect.step("web_search_read"),
        );
        await mountView({
            resModel: "event.registration",
            type,
            arch: ARCHES[type],
            context: { is_registration_desk_view: true },
        });
        expect.verifySteps(["web_search_read"]);
        await contains(
            type === "kanban" ? ".o_kanban_record" : ".o_data_row .o_data_cell",
        ).click();
        expect.verifySteps(["dialog registration", "web_search_read"]);
    });
}
