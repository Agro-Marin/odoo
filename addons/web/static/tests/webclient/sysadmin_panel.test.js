import { expect, test } from "@odoo/hoot";
import { animationFrame, mockDate } from "@odoo/hoot-mock";
import {
    mountWebClient,
    mountWithCleanup,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { session } from "@web/session";
import { SysAdminPanel } from "@web/webclient/home_menu/sysadmin_panel";

/**
 * @param {Object} params
 * @param {string|false} [params.warning]
 * @param {string} [params.warningType]
 * @param {string} [params.message]
 */
function withSession({ warning, warningType, message }) {
    patchWithCleanup(session, {
        warning,
        sysadmin_message: { message, warning_type: warningType },
    });
}

test("no panel when the reader has no warning level", async () => {
    withSession({ warning: false, warningType: "user", message: "hello" });
    await mountWithCleanup(SysAdminPanel);
    expect("div:contains(hello)").toHaveCount(0);
});

test("no panel when the message names no audience", async () => {
    withSession({ warning: "admin", warningType: undefined, message: "hello" });
    await mountWithCleanup(SysAdminPanel);
    expect("div:contains(hello)").toHaveCount(0);
});

test("a message aimed at users is shown to a non-admin reader", async () => {
    withSession({
        warning: "user",
        warningType: "user",
        message: "scheduled downtime",
    });
    await mountWithCleanup(SysAdminPanel);
    expect("div:contains(scheduled downtime)").toHaveCount(1);
});

test("a message aimed at admins is hidden from a non-admin reader", async () => {
    withSession({ warning: "user", warningType: "admin", message: "admins only" });
    await mountWithCleanup(SysAdminPanel);
    expect("div:contains(admins only)").toHaveCount(0);
});

test("a message aimed at admins is shown to an admin reader", async () => {
    withSession({ warning: "admin", warningType: "admin", message: "admins only" });
    await mountWithCleanup(SysAdminPanel);
    expect("div:contains(admins only)").toHaveCount(1);
});

test("an audience the client does not recognise is hidden from a user reader", async () => {
    withSession({ warning: "user", warningType: "everyone", message: "who knows" });
    await mountWithCleanup(SysAdminPanel);
    expect("div:contains(who knows)").toHaveCount(0);
});

test("an audience the client does not recognise is hidden from an admin too", async () => {
    withSession({ warning: "admin", warningType: "everyone", message: "who knows" });
    await mountWithCleanup(SysAdminPanel);
    expect("div:contains(who knows)").toHaveCount(0);
});

test("markup in the message renders as HTML, not as visible markup", async () => {
    withSession({
        warning: "user",
        warningType: "user",
        message: "<b>maintenance</b>",
    });
    await mountWithCleanup(SysAdminPanel);
    expect("div b").toHaveCount(1);
    expect("div b").toHaveText("maintenance");
});

test("an expired database still shows a user-audience message to a non-admin", async () => {
    mockDate("2019-10-10T12:00:00");
    patchWithCleanup(session, {
        expiration_date: "2019-10-08 12:00:00",
        expiration_reason: "trial",
        storeData: true,
        warning: "user",
        sysadmin_message: { message: "migration in progress", warning_type: "user" },
    });
    await mountWebClient();
    await animationFrame();
    expect(".d-flex > div:contains(migration in progress)").toHaveCount(1);
});
