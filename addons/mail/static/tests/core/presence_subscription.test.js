import { defineMailModels, start, startServer } from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-dom";
import { getService, patchWithCleanup } from "@web/../tests/web_test_helpers";

describe.current.tags("headless");
defineMailModels();

function trackChannelClaims() {
    const added = [];
    const deleted = [];
    patchWithCleanup(getService("bus_service"), {
        addChannel(channel) {
            added.push(channel);
            return super.addChannel(channel);
        },
        deleteChannel(channel) {
            deleted.push(channel);
            return super.deleteChannel(channel);
        },
    });
    return { added, deleted };
}

test("a presence channel is never released unless it was claimed (res.partner)", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "Ghost" });
    await start();
    const { added, deleted } = trackChannelClaims();
    const store = getService("mail.store");
    const partner = store["res.partner"].insert({ id: partnerId, is_public: true });
    await animationFrame();
    expect(deleted).toEqual([]);
    partner.is_public = false;
    await animationFrame();
    expect(deleted.filter((channel) => !added.includes(channel))).toEqual([]);
});

test("a presence channel is never released unless it was claimed (mail.guest)", async () => {
    const pyEnv = await startServer();
    const guestId = pyEnv["mail.guest"].create({ name: "Visitor" });
    await start();
    const { added, deleted } = trackChannelClaims();
    const store = getService("mail.store");
    const guest = store["mail.guest"].insert({ id: guestId, name: "Visitor" });
    await animationFrame();
    expect(deleted).toEqual([]);
    guest.im_status_access_token = "tok";
    await animationFrame();
    expect(deleted.filter((channel) => !added.includes(channel))).toEqual([]);
});
