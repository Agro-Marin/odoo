import { waitUntilSubscribe } from "@bus/../tests/bus_test_helpers";
import { defineMailModels, start, startServer } from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import { runAllTimers } from "@odoo/hoot-mock";
import { getService, serverState } from "@web/../tests/web_test_helpers";

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
