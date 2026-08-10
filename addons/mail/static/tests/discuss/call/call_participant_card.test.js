import { defineMailModels, start, startServer } from "@mail/../tests/mail_test_helpers";
import { CallParticipantCard } from "@mail/discuss/call/common/call_participant_card";
import { describe, expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { getService, mountWithCleanup } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");
defineMailModels();

const SELF_SESSION_ID = 1;
const REMOTE_SESSION_ID = 2;

/**
 * A call where the local user AND a remote participant are both screen
 * sharing, with the LOCAL upload paused — what dismissing the infinite
 * mirroring warning leaves behind. `Thread.visibleCards` really does emit a
 * `type: "screen"` card per sharing session, so both cards below are the ones
 * the Call view would mount.
 */
async function setupPausedScreenShare() {
    const pyEnv = await startServer();
    const channelId = pyEnv["discuss.channel"].create({ name: "General" });
    await start();
    const store = getService("mail.store");
    const thread = store.Thread.insert({ model: "discuss.channel", id: channelId });
    const makeSession = (id) => {
        const session = store["discuss.channel.rtc.session"].insert({
            id,
            channel_member_id: {
                id: 1000 + id,
                channel_id: thread,
                partner_id: { id: 2000 + id, name: `P${id}` },
            },
            is_screen_sharing_on: true,
        });
        // a real MediaStream: the card mounts a <video> and assigns srcObject
        session.videoStreams.set("screen", new MediaStream());
        return session;
    };
    const selfSession = makeSession(SELF_SESSION_ID);
    const remoteSession = makeSession(REMOTE_SESSION_ID);
    thread.rtc_session_ids = [selfSession, remoteSession];
    const rtc = getService("discuss.rtc");
    rtc.localSession = selfSession;
    // `is_screen_sharing_on` stays true while paused: it is derived from the
    // track existing, not from `enabled`.
    rtc.state.screenTrack = { enabled: false, stop: () => {} };
    return { thread };
}

async function mountScreenCardFor(thread, sessionId) {
    const cardData = thread.visibleCards.find(
        (card) => card.type === "screen" && card.session.id === sessionId,
    );
    expect(Boolean(cardData)).toBe(true);
    await mountWithCleanup(CallParticipantCard, {
        props: { className: "", cardData, thread },
    });
    await animationFrame();
}

test("the paused-stream overlay is shown on the self screen-share card", async () => {
    const { thread } = await setupPausedScreenShare();
    await mountScreenCardFor(thread, SELF_SESSION_ID);
    expect("button:contains('Stream paused')").toHaveCount(1);
});

test("the paused-stream overlay is NOT shown on another participant's screen-share card", async () => {
    // The local track being paused says nothing about a remote's stream. The
    // template condition only tested `rtc.state.screenTrack.enabled`, a LOCAL
    // field, so every remote screen tile was replaced by a "Stream paused /
    // Resume stream" button that resumed the LOCAL upload when clicked.
    const { thread } = await setupPausedScreenShare();
    await mountScreenCardFor(thread, REMOTE_SESSION_ID);
    expect("button:contains('Stream paused')").toHaveCount(0);
});
