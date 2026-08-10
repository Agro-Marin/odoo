import {
    contains,
    defineMailModels,
    openDiscuss,
    start,
    startServer,
} from "@mail/../tests/mail_test_helpers";
import { Message } from "@mail/core/common/message";
import { LONG_PRESS_DELAY } from "@mail/utils/common/hooks";
import { describe, expect, test } from "@odoo/hoot";
import { queryOne, runAllTimers } from "@odoo/hoot-dom";
import { advanceTime, mockUserAgent } from "@odoo/hoot-mock";
import { status } from "@odoo/owl";
import { getService, patchWithCleanup } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");
defineMailModels();

function touchStart(selector) {
    const ev = new Event("touchstart", { bubbles: true });
    ev.touches = [{ clientX: 0, clientY: 0 }];
    queryOne(selector).dispatchEvent(ev);
}

/**
 * Record every `openMobileActions` call with the component status at the time.
 * Asserting on the DOM instead would be vacuous: `optionsDropdown.open()` is an
 * inert write once the component is destroyed, so a post-destroy call opens
 * nothing and throws nothing — the call itself is the only observable.
 */
function trackMobileActions() {
    const statuses = [];
    patchWithCleanup(Message.prototype, {
        openMobileActions(ev) {
            statuses.push(status(this));
            return super.openMobileActions(ev);
        },
    });
    return statuses;
}

async function setupMobileMessage() {
    // isMobileOS() is read in Message.setup(), so the UA must be mocked before
    // anything mounts.
    mockUserAgent("android");
    const pyEnv = await startServer();
    const channelId = pyEnv["discuss.channel"].create({ name: "General" });
    const messageId = pyEnv["mail.message"].create({
        body: "hello",
        message_type: "comment",
        model: "discuss.channel",
        res_id: channelId,
    });
    await start();
    await openDiscuss(channelId);
    await contains(".o-mail-Message");
    return { messageId };
}

test("long press on a message opens its mobile action menu", async () => {
    // Positive control: the hook is registered behind `isMobileOS()`, so
    // without this the unmount test could pass with nothing listening at all.
    const statuses = trackMobileActions();
    await setupMobileMessage();
    touchStart(".o-mail-Message");
    await advanceTime(LONG_PRESS_DELAY);
    expect(statuses).toEqual(["mounted"]);
    // the menu is portalled into the overlay container, not nested in the message
    await contains(".dropdown-menu");
});

test("a message unmounted mid-long-press does not run its action", async () => {
    const statuses = trackMobileActions();
    const { messageId } = await setupMobileMessage();
    touchStart(".o-mail-Message");
    // The message goes away inside the press window — a deletion, a thread
    // switch or a chat window close all do this. `touchend`/`touchcancel` can
    // no longer cancel the timer: those listeners left with the component.
    getService("mail.store")["mail.message"].get(messageId).delete();
    await contains(".o-mail-Message", { count: 0 });
    await runAllTimers();
    // Without `onWillUnmount(reset)` this records ["destroyed"]. Nothing is
    // visibly broken today — the dropdown write is inert on a destroyed
    // component — but the hook is shared, and a consumer whose action has real
    // side effects would run them against a torn-down component.
    expect(statuses).toEqual([]);
    await contains(".dropdown-menu", { count: 0 });
});
