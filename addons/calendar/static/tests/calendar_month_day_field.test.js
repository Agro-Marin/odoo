import "@calendar/views/fields/calendar_month_day_field";

import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import {
    clickSave,
    defineModels,
    editSelectMenu,
    fields,
    models,
    mountView,
    onRpc,
} from "@web/../tests/web_test_helpers";

class Recurrence extends models.Model {
    day = fields.Integer();
    _records = [
        { id: 1, day: 15 },
        { id: 2, day: -1 },
    ];
}

defineModels([Recurrence]);

test("the last day of the month is picked by name, and saved as -1", async () => {
    onRpc("web_save", ({ args }) => expect.step(args[1]));
    await mountView({
        type: "form",
        resModel: "recurrence",
        resId: 1,
        arch: `<form><field name="day" widget="calendar_month_day"/></form>`,
    });
    expect(".o_field_widget[name='day'] input").toHaveValue("15");
    await editSelectMenu(".o_field_widget[name='day'] input", { value: "Last day" });
    await animationFrame();
    await clickSave();
    expect.verifySteps([{ day: -1 }]);
});

test("a stored -1 reads as the last day of the month", async () => {
    await mountView({
        type: "form",
        resModel: "recurrence",
        resId: 2,
        arch: `<form edit="0"><field name="day" widget="calendar_month_day"/></form>`,
    });
    expect(".o_field_widget[name='day']").toHaveText("Last day");
});
