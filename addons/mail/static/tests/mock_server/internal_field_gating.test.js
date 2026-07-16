import { defineMailModels, start, startServer } from "@mail/../tests/mail_test_helpers";
import { withGuest } from "@mail/../tests/mock_server/mail_mock_server";
import { describe, expect, test } from "@odoo/hoot";
import { Command, serverState } from "@web/../tests/web_test_helpers";
import { rpc } from "@web/core/network/rpc";

describe.current.tags("desktop");
defineMailModels();

/**
 * The JS mock server mirrors the Python Store field gating: email_from is
 * emitted only for an internal target (or an authorless message) and
 * notification_ids only for an internal target. These are exercised as the
 * internal user by the contract gate; this pins the GUEST-facing side (a
 * guest must never receive those fields), which the contract gate — running
 * as the internal admin — cannot cover.
 */
async function seed() {
    const pyEnv = await startServer();
    const bobPartnerId = pyEnv["res.partner"].create({ name: "Bob" });
    pyEnv["res.users"].create({ login: "bob", name: "Bob", partner_id: bobPartnerId });
    const guestId = pyEnv["mail.guest"].create({ name: "Visitor" });
    const channelId = pyEnv["discuss.channel"].create({
        channel_type: "group",
        channel_member_ids: [
            Command.create({ partner_id: serverState.partnerId }),
            Command.create({ partner_id: bobPartnerId }),
            Command.create({ guest_id: guestId }),
        ],
        name: "Group",
    });
    const [subtypeCommentId] = pyEnv["mail.message.subtype"].search([
        ["subtype_xmlid", "=", "mail.mt_comment"],
    ]);
    const messageId = pyEnv["mail.message"].create({
        author_id: bobPartnerId,
        body: "Hello",
        email_from: "bob@example.com",
        message_type: "comment",
        model: "discuss.channel",
        res_id: channelId,
        subtype_id: subtypeCommentId,
    });
    pyEnv["mail.notification"].create({
        mail_message_id: messageId,
        notification_status: "sent",
        notification_type: "inbox",
        res_partner_id: bobPartnerId,
    });
    await start();
    return { channelId, guestId, messageId };
}

test("internal user receives email_from and notification_ids", async () => {
    const { channelId, messageId } = await seed();
    const { data } = await rpc("/discuss/channel/messages", {
        channel_id: channelId,
        fetch_params: { limit: 30 },
    });
    const message = data["mail.message"].find((m) => m.id === messageId);
    expect("email_from" in message).toBe(true);
    expect("notification_ids" in message).toBe(true);
});

test("guest does not receive email_from or notification_ids", async () => {
    const { channelId, guestId, messageId } = await seed();
    const { data } = await withGuest(guestId, () =>
        rpc("/discuss/channel/messages", {
            channel_id: channelId,
            fetch_params: { limit: 30 },
        }),
    );
    const message = data["mail.message"].find((m) => m.id === messageId);
    // internal-only fields must be withheld from a guest, matching the
    // Python controller (mail_message.py _to_store predicates)
    expect("email_from" in message).toBe(false);
    expect("notification_ids" in message).toBe(false);
});
