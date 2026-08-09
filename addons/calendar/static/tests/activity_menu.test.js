import { defineCalendarModels } from "@calendar/../tests/calendar_test_helpers";
import { click, contains, start, startServer } from "@mail/../tests/mail_test_helpers";
import { test } from "@odoo/hoot";
import { mockDate } from "@odoo/hoot-mock";
import {
    asyncStep,
    mockService,
    preloadFullCalendar,
    serverState,
    waitForSteps,
} from "@web/../tests/web_test_helpers";

defineCalendarModels();
preloadFullCalendar();

// Known: this test fails when it runs after `@calendar/activity` in the *same*
// page load, and passes isolated -- which is how CI runs suites, so CI is green.
// Ruled out, so nobody re-derives it: the server side is not the cause. Probed in
// both orders, `_systray_get_calendar_event_domain()` matches the same two events
// and `_get_activity_groups()` returns the same "Today's Meetings" group; only the
// rendering differs. It is also not `registerArchs`, the one global that
// `@calendar/activity` touches (removing it changes nothing here). The remaining
// suspect is state the mail Store keeps across a page load. Note this is a
// different problem from the `FIXME` in the mock server's
// `_systray_get_calendar_event_domain`, which is about its commented-out allday
// clause.
test("activity menu widget:today meetings", async () => {
    // `mockDate(date, tz)`, not `mockDate(y, m, d, h, m, s)`: the old signature
    // is silently accepted -- a non-string first argument has no `.year`, so
    // every field falls back to hoot's default date and the `3` is taken as the
    // *timezone*. The date this test thought it had pinned was never pinned, so
    // it passed or failed depending on what the previously-run suite had left
    // mocked.
    mockDate("2018-04-20 06:00:00", 0);
    const pyEnv = await startServer();
    const attendeeId = pyEnv["calendar.attendee"].create({ partner_id: serverState.partnerId });
    pyEnv["calendar.event"].create([
        {
            res_model: "calendar.event",
            name: "meeting1",
            start: "2018-04-20 06:30:00",
            attendee_ids: [attendeeId],
        },
        {
            res_model: "calendar.event",
            name: "meeting2",
            start: "2018-04-20 09:30:00",
            attendee_ids: [attendeeId],
        },
    ]);
    mockService("action", {
        doAction(action) {
            if (typeof action === "string") {
                asyncStep(action);
            }
        },
    });
    await start();
    await contains(".o_menu_systray i[aria-label='Activities']");
    await click(".o_menu_systray i[aria-label='Activities']");
    await contains(".o-mail-ActivityGroup div[name='activityTitle']", { text: "Today's Meetings" });
    await contains(".o-mail-ActivityGroup .o-calendar-meeting", { count: 2 });
    await contains(".o-calendar-meeting span.fw-bold", { text: "meeting1" });
    await contains(".o-calendar-meeting span:not(.fw-bold)", { text: "meeting2" });
    await click(".o-mail-ActivityMenu .o-mail-ActivityGroup");
    await waitForSteps(["calendar.action_calendar_event"]);
});
