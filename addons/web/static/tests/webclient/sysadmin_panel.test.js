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
 * The panel had no tests at all, and that gap was not academic: an audit round
 * claimed it escaped its HTML, traced the OWL rendering chain to "confirm" it,
 * and was only refuted later by reading `enterprise_subscription_service`, which
 * wraps the message in `markup()` before the panel ever sees it. The last test
 * here is the one that would have settled it in a second.
 *
 * `showMessage` reads TWO different things whose names look alike:
 * `warningType` is the reader's own level, from `session.warning`, while
 * `sysadmin.warning_type` is who the message is aimed at.
 */
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

test("markup in the message renders as HTML, not as visible markup", async () => {
    // The assertion that refutes the bad finding: the service marks the message
    // up, so `t-out` renders it rather than escaping it.
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
    // The blocked-UI mount used to add `warningType === "admin"` on top of
    // `showMessage`, conflating the READER's level with the message's AUDIENCE.
    // The effect was that the message explaining why the UI is blocked was
    // hidden from every non-admin internal user, exactly when it matters.
    mockDate("2019-10-10T12:00:00");
    patchWithCleanup(session, {
        expiration_date: "2019-10-08 12:00:00", // already past -> daysLeft <= 0
        expiration_reason: "trial",
        storeData: true,
        warning: "user", // a non-admin internal reader
        sysadmin_message: { message: "migration in progress", warning_type: "user" },
    });
    await mountWebClient();
    await animationFrame();
    // Anchored on the blocked-UI wrapper's own class: with the whole webclient
    // mounted, ":contains" also matches every ancestor div, so a bare count
    // here measures the wrapper nesting rather than the panel.
    expect(".d-flex > div:contains(migration in progress)").toHaveCount(1);
});
