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
// It is not a calendar bug, and the diagnosis is written down here so nobody
// spends the afternoon re-deriving it.
//
// Instrumenting the mock's `_get_activity_groups` shows that in the failing
// order it is called exactly twice during this test's `start()`, and both calls
// see the *previous* test's server state: one `calendar.event` (activity.test's
// "meeting1"), one `calendar.attendee` whose partner is activity.test's freshly
// created partner rather than `serverState.partnerId`. This test's own two
// events and its attendee -- which exist, `startServer()` having created them
// before `start()` -- are never queried at all. The client store therefore ends
// up with `activityGroups == []` and the systray has nothing to render.
//
// So the second test's boot fetch is served against the first test's server
// state, and the second store's `systray_get_activities` fetch never reaches the
// server. That is an isolation defect in the mail store / test harness, above
// this module. Ruled out on the way: the calendar mock itself (called directly
// at the end of the test, `_systray_get_calendar_event_domain()` matches both
// events and `_get_activity_groups()` returns the group, in both orders), and
// `registerArchs`, the single global `@calendar/activity` touches.
//
// Unrelated to the `FIXME` in the mock server's
// `_systray_get_calendar_event_domain`, which is about its commented-out allday
// clause and is easy to mistake for this.
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
