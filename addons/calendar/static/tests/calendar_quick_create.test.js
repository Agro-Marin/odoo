import { defineCalendarModels } from "@calendar/../tests/calendar_test_helpers";
import { CalendarQuickCreateFormController } from "@calendar/views/calendar_form/calendar_quick_create";
import { expect, test } from "@odoo/hoot";
import { mockDate } from "@odoo/hoot-mock";
import { mountView, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { luxon } from "@web/core/l10n/luxon";

defineCalendarModels();

test("More Options forwards the duration the quick create recomputed", async () => {
    mockDate("2016-12-12 08:00:00", 0);
    let controller;
    patchWithCleanup(CalendarQuickCreateFormController.prototype, {
        setup() {
            super.setup(...arguments);
            controller = this;
        },
    });
    await mountView({
        type: "form",
        resModel: "calendar.event",
        arch: `
            <form js_class="calendar_quick_create_form_view">
                <field name="name"/>
                <field name="start"/>
                <field name="stop"/>
                <field name="duration" invisible="1" force_save="1"/>
            </form>`,
        context: { default_duration: 2 },
    });
    const actions = [];
    controller.actionService = {
        doAction: (action, options) => actions.push({ action, options }),
    };
    // the drag gave 10:00-12:00; the user moved the end to 14:00 and the
    // server-side compute set duration to 4
    await controller.model.root.update({
        start: luxon.DateTime.fromISO("2016-12-12T10:00:00"),
        stop: luxon.DateTime.fromISO("2016-12-12T14:00:00"),
        duration: 4,
    });
    await controller.goToFullEvent();
    expect(actions).toHaveLength(1);
    expect(actions[0].options.additionalContext.default_duration).toBe(4);
    expect(actions[0].options.additionalContext.default_stop).toBe(
        "2016-12-12 14:00:00",
    );
});
