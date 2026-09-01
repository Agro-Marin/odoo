import { describe, expect, test } from "@odoo/hoot";
import { click, waitFor } from "@odoo/hoot-dom";
import {
    MockServer,
    mountWithCleanup,
    patchWithCleanup,
    serverState,
} from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { WebClient } from "@web/webclient/webclient";

import { defineBusModels } from "@bus/../tests/bus_test_helpers";

defineBusModels();
describe.current.tags("desktop");

// The payload iap.account._send_no_credit_notification actually puts on the bus:
// a title, no message, and the URL to buy more credits. See
// addons/iap_mail/models/iap_account.py:34.
const NO_CREDIT_PAYLOAD = {
    type: "no_credit",
    title: "Not enough credits for Snail Mail",
    get_credits_url: "https://iap.example/buy?service=snailmail",
};

test("the out-of-credits notification offers the credits link as a button", async () => {
    await mountWithCleanup(WebClient);
    MockServer.env["bus.bus"]._sendone(
        serverState.partnerId,
        "iap_notification",
        NO_CREDIT_PAYLOAD,
    );
    await waitFor(".o_notification");
    expect(".o_notification_content").toHaveText("Not enough credits for Snail Mail");
    expect(".o_notification_buttons button").toHaveText("Buy more credits");
    // The affordance must live in the notification's own button area, not as an
    // anchor buried in the middle of the message text.
    expect(".o_notification_content a").toHaveCount(0);
});

test("clicking the credits button opens the buy URL in a new tab", async () => {
    const opened = [];
    patchWithCleanup(browser, {
        open: (url, target) => opened.push([url, target]),
    });
    await mountWithCleanup(WebClient);
    MockServer.env["bus.bus"]._sendone(
        serverState.partnerId,
        "iap_notification",
        NO_CREDIT_PAYLOAD,
    );
    await waitFor(".o_notification_buttons button");
    await click(".o_notification_buttons button");
    expect(opened).toEqual([["https://iap.example/buy?service=snailmail", "_blank"]]);
});
