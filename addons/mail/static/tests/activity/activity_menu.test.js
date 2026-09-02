import {
    click,
    contains,
    defineMailModels,
    start,
    startServer,
    triggerHotkey,
} from "@mail/../tests/mail_test_helpers";
import { ActivityMenu } from "@mail/core/web/activity_menu";
import { describe, expect, test } from "@odoo/hoot";
import { animationFrame, queryText } from "@odoo/hoot-dom";
import { mockService, mountWithCleanup } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");
defineMailModels();

test("should update activities when opening the activity menu", async () => {
    const pyEnv = await startServer();
    await start();
    await contains(".o_menu_systray i[aria-label='Activities']");
    await contains(".o-mail-ActivityMenu-counter", { count: 0 });
    const partnerId = pyEnv["res.partner"].create({});
    pyEnv["mail.activity"].create({
        res_id: partnerId,
        res_model: "res.partner",
    });
    await click(".o_menu_systray i[aria-label='Activities']");
    await contains(".o-mail-ActivityMenu-counter", { text: "1" });
});

test("global shortcut", async () => {
    await mountWithCleanup(ActivityMenu);
    await triggerHotkey("control+k");
    await animationFrame();
    expect(queryText(`.o_command:contains("Activity") .o_command_hotkey`)).toEqual(
        "Activity\nALT + SHIFT + A",
        { message: "The command should be registered with the right hotkey" },
    );
    await triggerHotkey("alt+shift+a");
    await animationFrame();
    expect(".modal-dialog .modal-title").toHaveText("Schedule Activity");
});

test("document-less activity group redirects with the My/Today/Late filters", async () => {
    /** @type {any[]} */
    const opened = [];
    mockService("action", {
        doAction(action, options) {
            opened.push([action, options]);
        },
    });
    await start();
    const menu = await mountWithCleanup(ActivityMenu);
    menu.openActivityGroup({
        id: 1,
        model: "mail.activity",
        name: "Other activities",
        activity_ids: [1, 2],
    });
    expect(opened.length).toBe(1);
    const [action, options] = opened[0];
    expect(action).toBe("mail.mail_activity_without_access_action");
    // The redirection must carry the same defaults every other systray entry
    // gets, instead of opening every document-less activity unfiltered.
    expect(options.additionalContext).toEqual({
        force_search_count: 1,
        search_default_filter_activities_my: 1,
        search_default_activities_overdue: 1,
        search_default_activities_today: 1,
        active_ids: [1, 2],
        active_model: "mail.activity",
    });
});
