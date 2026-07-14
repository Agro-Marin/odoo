import { waitUntilSubscribe } from "@bus/../tests/bus_test_helpers";
import {
    defineMailModels,
    listenStoreFetch,
    start,
    startServer,
    waitStoreFetch,
} from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import { runAllTimers } from "@odoo/hoot-mock";
import { Command, getService, serverState } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");
defineMailModels();

test("channels are refetched when a channel message is deleted", async () => {
    const pyEnv = await startServer();
    const channelId = pyEnv["discuss.channel"].create({
        channel_member_ids: [Command.create({ partner_id: serverState.partnerId })],
        name: "General",
    });
    const messageId = pyEnv["mail.message"].create({
        body: "Hello",
        message_type: "comment",
        model: "discuss.channel",
        res_id: channelId,
    });
    listenStoreFetch("channels_as_member");
    const env = await start();
    const store = getService("mail.store");
    await store.channels.fetch();
    await waitStoreFetch("channels_as_member");
    expect(store.channels.status).toBe("fetched");
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
    // the cached channel data must be invalidated and fetched again, so unread
    // counters are resynchronized with the server
    await waitStoreFetch("channels_as_member");
    // the step is registered when the mock server receives the request: await
    // the in-flight fetch itself before asserting the final status
    await store.channels.fetch();
    expect(store.channels.status).toBe("fetched");
});
