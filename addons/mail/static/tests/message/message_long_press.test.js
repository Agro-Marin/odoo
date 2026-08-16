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
    const statuses = trackMobileActions();
    await setupMobileMessage();
    touchStart(".o-mail-Message");
    await advanceTime(LONG_PRESS_DELAY);
    expect(statuses).toEqual(["mounted"]);
    await contains(".dropdown-menu");
});

test("a message unmounted mid-long-press does not run its action", async () => {
    const statuses = trackMobileActions();
    const { messageId } = await setupMobileMessage();
    touchStart(".o-mail-Message");
    getService("mail.store")["mail.message"].get(messageId).delete();
    await contains(".o-mail-Message", { count: 0 });
    await runAllTimers();
    expect(statuses).toEqual([]);
    await contains(".dropdown-menu", { count: 0 });
});
