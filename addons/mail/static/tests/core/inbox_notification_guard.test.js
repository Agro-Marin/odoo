import { defineMailModels, start, startServer } from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import { waitUntil } from "@odoo/hoot-dom";
import { getService, serverState } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");
defineMailModels();

test("an inbox notification whose message is absent from store_data still counts", async () => {
    const pyEnv = await startServer();
    await start();
    const store = getService("mail.store");
    await store.isReady;
    const before = store.inbox.counter;
    const [partner] = pyEnv["res.partner"].read(serverState.partnerId);
    pyEnv["bus.bus"]._sendone(partner, "mail.message/inbox", {
        message_id: 4242,
        store_data: {},
    });
    await waitUntil(() => store.inbox.counter === before + 1);
    expect(store.inbox.messages).toHaveLength(0);
});
