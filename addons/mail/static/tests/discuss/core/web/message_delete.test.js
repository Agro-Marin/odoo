import { waitUntilSubscribe } from "@bus/../tests/bus_test_helpers";
import {
    defineMailModels,
    listenStoreFetch,
    onRpcBefore,
    start,
    startServer,
    waitStoreFetch,
} from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import { animationFrame, runAllTimers } from "@odoo/hoot-mock";
import { Command, getService, serverState } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");
defineMailModels();

test("no channel refetch on message deletion once channels are fetched", async () => {
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
    let channelFetchCount = 0;
    onRpcBefore("/mail/data", (args) => {
        if (JSON.stringify(args.fetch_params ?? []).includes("channels_as_member")) {
            channelFetchCount++;
        }
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
    // liveness check on the counter itself: the explicit fetch above must
    // have been counted, otherwise the final assertion would be vacuous
    expect(channelFetchCount).toBe(1);
    const fetchesBeforeDelete = channelFetchCount;
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
    await runAllTimers();
    await animationFrame();
    // the deletion itself is processed...
    expect(store["mail.message"].get(messageId)).toBe(undefined);
    // ...but with the channel list already fetched, thread state derives
    // from Thread records which the bus-fenced counter delta keeps current:
    // the cached channel data must NOT be refetched (one deletion in a busy
    // database would otherwise refetch every client's whole channel list)
    expect(channelFetchCount).toBe(fetchesBeforeDelete);
    expect(store.channels.status).toBe("fetched");
});
