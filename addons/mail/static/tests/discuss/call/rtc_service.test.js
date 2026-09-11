// @ts-check
import { defineMailModels, start } from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";

describe.current.tags("desktop");
defineMailModels();

test("network broadcasts only advance sequence from a numeric message field", async () => {
    const env = await start();
    const store = env.services["mail.store"];
    const session = store["discuss.channel.rtc.session"].insert({ id: 42 });
    session.sequence = 1;
    for (const message of [
        null,
        undefined,
        "ping",
        0,
        {},
        { sequence: "7" },
        { sequence: 0 },
    ]) {
        await store.rtc._onNetworkBroadcast({ senderId: session.id, message });
        expect(session.sequence).toBe(1);
    }
    await store.rtc._onNetworkBroadcast({
        senderId: session.id,
        message: { sequence: 7 },
    });
    expect(session.sequence).toBe(7);
    await store.rtc._onNetworkBroadcast({
        senderId: session.id,
        message: { sequence: 3 },
    });
    expect(session.sequence).toBe(7);
});
