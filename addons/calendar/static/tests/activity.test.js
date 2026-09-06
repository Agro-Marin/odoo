import { defineCalendarModels } from "@calendar/../tests/calendar_test_helpers";
import {
    click,
    contains,
    openFormView,
    registerArchs,
    start,
    startServer,
} from "@mail/../tests/mail_test_helpers";
import { test } from "@odoo/hoot";
import { preloadFullCalendar } from "@web/../tests/web_test_helpers";

defineCalendarModels();
preloadFullCalendar();

/**
 * Create a partner with a meeting activity linked to a calendar event, the
 * shared fixture both tests below exercise.
 */
function createMeetingWithActivity(pyEnv, { partnerName } = {}) {
    const partnerId = pyEnv["res.partner"].create(partnerName ? { name: partnerName } : {});
    const activityTypeId = pyEnv["mail.activity.type"].create({
        icon: "fa-calendar",
        name: "Meeting",
    });
    const attendeeId = pyEnv["calendar.attendee"].create({
        partner_id: partnerId,
    });
    const calendarMeetingId = pyEnv["calendar.event"].create({
        res_model: "calendar.event",
        name: "meeting1",
        start: "2022-07-06 06:30:00",
        attendee_ids: [attendeeId],
    });
    pyEnv["mail.activity"].create({
        name: "Small Meeting",
        activity_type_id: activityTypeId,
        can_write: true,
        res_id: partnerId,
        res_model: "res.partner",
        calendar_event_id: calendarMeetingId,
    });
    return partnerId;
}

test("activity click on Reschedule", async () => {
    registerArchs({
        "calendar.event,false,calendar": `<calendar date_start="start"/>`,
    });
    const pyEnv = await startServer();
    const partnerId = createMeetingWithActivity(pyEnv);
    await start();
    await openFormView("res.partner", partnerId);
    await click(".btn", { text: "Reschedule" });
    await contains(".o_calendar_view");
});

test("Can cancel activity linked to an event", async () => {
    const pyEnv = await startServer();
    const partnerId = createMeetingWithActivity(pyEnv, { partnerName: "Milan Kundera" });
    await start();
    await openFormView("res.partner", partnerId);
    await click(".o-mail-Activity .btn", { text: "Cancel" });
    await contains(".o-mail-Activity", { count: 0 });
});
