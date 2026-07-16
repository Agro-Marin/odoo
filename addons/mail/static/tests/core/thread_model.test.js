import { waitUntilSubscribe } from "@bus/../tests/bus_test_helpers";
import { defineMailModels, start, startServer } from "@mail/../tests/mail_test_helpers";
import { applyCounterAbsolute } from "@mail/utils/common/counters";
import { describe, expect, test } from "@odoo/hoot";
import { runAllTimers } from "@odoo/hoot-mock";
import {
    getService,
    makeServerError,
    onRpc,
    serverState,
} from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");
defineMailModels();

test("fetchNewMessages keeps thread messages in ascending id order", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "John" });
    const messageIds = pyEnv["mail.message"].create([
        { body: "message 1", model: "res.partner", res_id: partnerId },
        { body: "message 2", model: "res.partner", res_id: partnerId },
        { body: "message 3", model: "res.partner", res_id: partnerId },
    ]);
    await start();
    const store = getService("mail.store");
    const thread = store.Thread.insert({ id: partnerId, model: "res.partner" });
    // a message already known before the initial fetch (e.g. received from a
    // bus notification): it may be newer than some fetched messages
    const knownMessage = store["mail.message"].insert({
        id: messageIds[1],
        thread: { id: partnerId, model: "res.partner" },
    });
    thread.messages.add(knownMessage);
    await thread.fetchNewMessages();
    expect(thread.messages.map((message) => message.id)).toEqual(
        [...messageIds].sort((id1, id2) => id1 - id2),
    );
});

test("thread needaction counter decrements when needaction message is deleted", async () => {
    const pyEnv = await startServer();
    pyEnv["res.users"].write(serverState.userId, { notification_type: "inbox" });
    const partnerId = pyEnv["res.partner"].create({ name: "John" });
    const messageId = pyEnv["mail.message"].create({
        body: "Needaction message",
        model: "res.partner",
        needaction: true,
        res_id: partnerId,
    });
    pyEnv["mail.notification"].create({
        mail_message_id: messageId,
        notification_status: "sent",
        notification_type: "inbox",
        res_partner_id: serverState.partnerId,
    });
    const env = await start();
    const store = getService("mail.store");
    store.insert({
        "mail.thread": [
            {
                id: partnerId,
                message_needaction_counter: 1,
                model: "res.partner",
            },
        ],
        "mail.message": [
            {
                id: messageId,
                needaction: true,
                thread: { id: partnerId, model: "res.partner" },
            },
        ],
    });
    const thread = store.Thread.get({ id: partnerId, model: "res.partner" });
    expect(thread.message_needaction_counter).toBe(1);
    env.services.bus_service.start();
    env.services.bus_service.forceUpdateChannels();
    await runAllTimers();
    await waitUntilSubscribe();
    const deleteHandled = new Promise((resolve) =>
        env.bus.addEventListener("mail.message/delete", () => resolve(), {
            once: true,
        }),
    );
    const [partner] = pyEnv["res.partner"].read(serverState.partnerId);
    pyEnv["bus.bus"]._sendone(partner, "mail.message/delete", {
        message_ids: [messageId],
    });
    await deleteHandled;
    expect(thread.message_needaction_counter).toBe(0);
});

/**
 * Insert a thread with one needaction message and matching counters, for the
 * markAllMessagesAsRead optimistic-update tests.
 */
async function setupNeedactionThread(pyEnv) {
    pyEnv["res.users"].write(serverState.userId, { notification_type: "inbox" });
    const partnerId = pyEnv["res.partner"].create({ name: "John" });
    const messageId = pyEnv["mail.message"].create({
        body: "Needaction message",
        model: "res.partner",
        needaction: true,
        res_id: partnerId,
    });
    pyEnv["mail.notification"].create({
        mail_message_id: messageId,
        notification_status: "sent",
        notification_type: "inbox",
        res_partner_id: serverState.partnerId,
    });
    await start();
    const store = getService("mail.store");
    store.insert({
        "mail.thread": [
            {
                id: partnerId,
                message_needaction_counter: 1,
                model: "res.partner",
            },
        ],
        "mail.message": [
            {
                id: messageId,
                needaction: true,
                thread: { id: partnerId, model: "res.partner" },
            },
        ],
    });
    const message = store["mail.message"].get(messageId);
    store.inbox.messages.add(message);
    store.inbox.counter = 1;
    return {
        message,
        store,
        thread: store.Thread.get({ id: partnerId, model: "res.partner" }),
    };
}

test("failed markAllMessagesAsRead rolls back the optimistic counter updates", async () => {
    const pyEnv = await startServer();
    onRpc("mail.message", "mark_all_as_read", () => {
        throw makeServerError({ message: "mark all boom" });
    });
    const { message, store, thread } = await setupNeedactionThread(pyEnv);
    await thread.markAllMessagesAsRead();
    // no correcting bus notification arrives on failure: the optimistic
    // update must be rolled back locally.
    expect(message.needaction).toBe(true);
    expect(store.inbox.counter).toBe(1);
    expect(thread.message_needaction_counter).toBe(1);
});

test("markAllMessagesAsRead rollback is skipped when a newer absolute snapshot landed", async () => {
    const pyEnv = await startServer();
    onRpc("mail.message", "mark_all_as_read", () => {
        throw makeServerError({ message: "mark all boom" });
    });
    const { store, thread } = await setupNeedactionThread(pyEnv);
    const promise = thread.markAllMessagesAsRead();
    // while the RPC is pending, absolute counter snapshots land from the bus
    // (newer bus id): the failure rollback must not overwrite them with the
    // stale pre-update values.
    applyCounterAbsolute(store.inbox, "counter", 5, 99);
    applyCounterAbsolute(thread, "message_needaction_counter", 0, 99);
    await promise;
    expect(store.inbox.counter).toBe(5);
    expect(thread.message_needaction_counter).toBe(0);
});

test("plain document threads answer the channel-behavior hooks with neutral defaults", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "John" });
    await start();
    const store = getService("mail.store");
    const thread = store.Thread.insert({ id: partnerId, model: "res.partner" });
    expect(thread.isChannelKind).toBe(false);
    expect(thread.isChatChannel).toBe(false);
    expect(thread.isDirectChat).toBe(false);
    expect(thread.canLeave).toBe(false);
    expect(thread.canUnpin).toBe(false);
    expect(thread.allowCalls).toBe(false);
    expect(thread.allowDescription).toBe(false);
    expect(thread.hasAttachmentPanel).toBe(false);
    expect(thread.supportsCustomChannelName).toBe(false);
    expect(thread.invitationLink).toBe(undefined);
    expect(thread.hasOptimisticPost).toBe(false);
    expect(thread.hasStartOfConversationBanner).toBe(false);
    expect(thread.chatWindowComposerType).toBe("note");
    expect(thread.computeDisplayToSelf()).toBe(false);
    expect(thread.computeCorrespondent()).toBe(undefined);
    expect(thread.membersThatCanSeen).toHaveLength(0);
    expect(thread.showCorrespondentCountry).toBe(false);
    expect(thread.imStatusMember).toBe(undefined);
    expect(thread.isChatWith(store.self)).toBe(false);
    expect(thread.newMessageSeparatorId).toBe(undefined);
    expect(thread.openChannel()).toBe(false);
    expect(thread.fullNameWithParent).toBe(thread.displayName);
    expect(thread._getActualModelName()).toBe("mail.thread");
    // no rename endpoint for document threads: the request is ignored
    await thread.rename("new name");
    expect(thread.displayName).toBe(thread.display_name);
});

test("channel threads answer the channel-behavior hooks channel-wise", async () => {
    const pyEnv = await startServer();
    const channelId = pyEnv["discuss.channel"].create({ name: "General" });
    await start();
    const store = getService("mail.store");
    const thread = await store.Thread.getOrFetch({
        id: channelId,
        model: "discuss.channel",
    });
    expect(thread.isChannelKind).toBe(true);
    expect(thread.hasOptimisticPost).toBe(true);
    expect(thread.hasAttachmentPanel).toBe(true);
    expect(thread.hasStartOfConversationBanner).toBe(true);
    expect(thread.chatWindowComposerType).toBe(undefined);
    expect(thread._getActualModelName()).toBe("discuss.channel");
});

test("a deleted message is not resurrected by a stale fetch response", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "John" });
    const messageId = pyEnv["mail.message"].create({
        body: "doomed",
        model: "res.partner",
        res_id: partnerId,
    });
    await start();
    const store = getService("mail.store");
    const thread = store.Thread.insert({ id: partnerId, model: "res.partner" });
    await thread.fetchNewMessages();
    expect(thread.messages).toHaveLength(1);
    // the deletion arrives via the bus...
    const [partner] = pyEnv["res.partner"].read(serverState.partnerId);
    pyEnv["bus.bus"]._sendone(partner, "mail.message/delete", {
        message_ids: [messageId],
    });
    await waitUntilSubscribe();
    await runAllTimers();
    expect(store["mail.message"].get(messageId)).toBe(undefined);
    expect(thread.messages).toHaveLength(0);
    // ...then a stale fetch response (computed before the deletion,
    // processed after) lands: last-write-wins ingestion used to resurrect
    // the message in the store and in the thread
    store.insert({
        "mail.message": [
            {
                id: messageId,
                body: "<p>doomed</p>",
                thread: { id: partnerId, model: "res.partner" },
            },
        ],
    });
    thread.messages.add({ id: messageId });
    expect(store["mail.message"].get(messageId)).toBe(undefined);
    expect(thread.messages).toHaveLength(0);
});
