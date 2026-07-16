import { defineMailModels, start, startServer } from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import { Command, serverState } from "@web/../tests/web_test_helpers";
import { rpc } from "@web/core/network/rpc";

describe.current.tags("desktop");
defineMailModels();

/**
 * The mock's /discuss/channel/messages must mirror the controller: mark
 * needaction messages done for a non-public user *unconditionally* — including
 * `around` fetches (the mock previously skipped those, so server and tests
 * disagreed on when messages get marked read).
 */
async function seedNeedaction() {
    const pyEnv = await startServer();
    const channelId = pyEnv["discuss.channel"].create({
        channel_type: "channel",
        channel_member_ids: [Command.create({ partner_id: serverState.partnerId })],
        name: "General",
    });
    const messageId = pyEnv["mail.message"].create({
        body: "Hello",
        message_type: "comment",
        model: "discuss.channel",
        needaction: true,
        res_id: channelId,
    });
    const notificationId = pyEnv["mail.notification"].create({
        mail_message_id: messageId,
        notification_status: "sent",
        notification_type: "inbox",
        res_partner_id: serverState.partnerId,
    });
    await start();
    return { pyEnv, channelId, notificationId };
}

test("channel messages fetch marks needaction done for an internal user", async () => {
    const { pyEnv, channelId, notificationId } = await seedNeedaction();
    await rpc("/discuss/channel/messages", {
        channel_id: channelId,
        fetch_params: { limit: 30 },
    });
    const [notification] = pyEnv["mail.notification"].read(notificationId);
    expect(notification.is_read).toBe(true);
});

test("an 'around' channel messages fetch also marks needaction done", async () => {
    const { pyEnv, channelId, notificationId } = await seedNeedaction();
    const [message] = pyEnv["mail.message"].search_read([
        ["model", "=", "discuss.channel"],
    ]);
    // the previous mock skipped set_message_done when `around` was set
    await rpc("/discuss/channel/messages", {
        channel_id: channelId,
        fetch_params: { around: message.id, limit: 30 },
    });
    const [notification] = pyEnv["mail.notification"].read(notificationId);
    expect(notification.is_read).toBe(true);
});
