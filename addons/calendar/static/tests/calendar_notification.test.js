import { defineCalendarModels } from "@calendar/../tests/calendar_test_helpers";
import { click, contains, start, startServer } from "@mail/../tests/mail_test_helpers";
import { expect, test } from "@odoo/hoot";
import {
    asyncStep,
    mockService,
    onRpc,
    preloadFullCalendar,
    serverState,
    waitForSteps,
} from "@web/../tests/web_test_helpers";

defineCalendarModels();
preloadFullCalendar();

test("can listen on bus and display notifications in DOM and click OK", async () => {
    const pyEnv = await startServer();
    onRpc("/calendar/notify_ack", () => asyncStep("notify_ack"));
    await start();
    pyEnv["bus.bus"]._sendone(serverState.partnerId, "calendar.alarm", [
        {
            alarm_id: 1,
            event_id: 2,
            title: "Meeting",
            message: "Very old meeting message",
            timer: 0,
            notify_at: "1978-04-14 12:45:00",
        },
    ]);
    await contains(".o_notification", { text: "Meeting. Very old meeting message" });
    await click(".o_notification_buttons button", { text: "OK" });
    await contains(".o_notification", { count: 0 });
    await waitForSteps(["notify_ack"]);
});

test("can listen on bus and display notifications in DOM and click Detail", async () => {
    mockService("action", {
        doAction(actionId) {
            asyncStep(actionId.type);
        },
    });
    const pyEnv = await startServer();
    await start();
    pyEnv["bus.bus"]._sendone(serverState.partnerId, "calendar.alarm", [
        {
            alarm_id: 1,
            event_id: 2,
            title: "Meeting",
            message: "Very old meeting message",
            timer: 0,
            notify_at: "1978-04-14 12:45:00",
        },
    ]);
    await contains(".o_notification", { text: "Meeting. Very old meeting message" });
    await click(".o_notification_buttons button", { text: "Details" });
    await contains(".o_notification", { count: 0 });
    await waitForSteps(["ir.actions.act_window"]);
});

test("can listen on bus and display notifications in DOM and click Snooze", async () => {
    const pyEnv = await startServer();
    onRpc("/calendar/notify_ack", () => asyncStep("notify_ack"));
    await start();
    pyEnv["bus.bus"]._sendone(serverState.partnerId, "calendar.alarm", [
        {
            alarm_id: 1,
            event_id: 2,
            title: "Meeting",
            message: "Very old meeting message",
            timer: 0,
            notify_at: "1978-04-14 12:45:00",
        },
    ]);
    await contains(".o_notification", { text: "Meeting. Very old meeting message" });
    await click(".o_notification button", { text: "Snooze" });
    await contains(".o_notification", { count: 0 });
    await waitForSteps([]);
});

test("alarm body renders as markup, not as escaped text", async () => {
    // The server sends the formatted time and the alarm body as HTML; the
    // notification renders `props.message` with `t-out`, which escapes a plain
    // string. This payload is verbatim from GET /calendar/notify.
    const pyEnv = await startServer();
    await start();
    pyEnv["bus.bus"]._sendone(serverState.partnerId, "calendar.alarm", [
        {
            alarm_id: 1,
            event_id: 2,
            title: "standup",
            message:
                "08/09/2026 at (08:15:13 PM To 09:15:13 PM) (UTC)<p>bring the deck</p>",
            timer: 0,
            notify_at: "2026-08-09 20:05:13",
        },
    ]);
    await contains(".o_notification_content p", { text: "bring the deck" });
    expect(document.querySelector(".o_notification_content").textContent).not.toInclude(
        "<p>",
    );
});
