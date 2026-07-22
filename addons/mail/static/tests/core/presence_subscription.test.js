import { defineMailModels, start, startServer } from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-dom";
import { getService, patchWithCleanup } from "@web/../tests/web_test_helpers";

describe.current.tags("headless");
defineMailModels();

/**
 * Record every bus channel claim/release so a release can be matched against
 * the claim that is supposed to precede it.
 */
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
    // Regression: `_triggerPresenceSubscription.onUpdate` recorded
    // `presenceChannel` into `previousPresencechannel` even on the branch where
    // it did NOT subscribe, so the next update released a claim this record
    // never took. bus_service refuses the release and logs
    // "deleteChannel(...) without a matching addChannel" -- and when another
    // consumer legitimately holds that same channel, the bogus release
    // decrements *its* refcount and silently unsubscribes it.
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "Ghost" });
    await start();
    const { added, deleted } = trackChannelClaims();
    const store = getService("mail.store");
    // is_public partners are not monitored: inserting one must claim nothing.
    const partner = store["res.partner"].insert({ id: partnerId, is_public: true });
    await animationFrame();
    expect(deleted).toEqual([]);
    // Flipping it to monitorable must not release the channel it never claimed.
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
    // The access token is part of the channel name, so receiving it moves the
    // guest to a new presence channel: the old one may only be released if it
    // was claimed in the first place.
    guest.im_status_access_token = "tok";
    await animationFrame();
    expect(deleted.filter((channel) => !added.includes(channel))).toEqual([]);
});
