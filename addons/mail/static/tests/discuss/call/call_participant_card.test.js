import { defineMailModels, start, startServer } from "@mail/../tests/mail_test_helpers";
import { CallParticipantCard } from "@mail/discuss/call/common/call_participant_card";
import { describe, expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { getService, mountWithCleanup } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");
defineMailModels();

const SELF_SESSION_ID = 1;
const REMOTE_SESSION_ID = 2;

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
        session.videoStreams.set("screen", new MediaStream());
        return session;
    };
    const selfSession = makeSession(SELF_SESSION_ID);
    const remoteSession = makeSession(REMOTE_SESSION_ID);
    thread.rtc_session_ids = [selfSession, remoteSession];
    const rtc = getService("discuss.rtc");
    rtc.localSession = selfSession;
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

test("the paused-stream panel is shown on the self screen-share card", async () => {
    const { thread } = await setupPausedScreenShare();
    await mountScreenCardFor(thread, SELF_SESSION_ID);
    expect("h1:contains('You are Presenting')").toHaveCount(1);
    // The two ways out of the infinite mirror, both on the card itself.
    expect("button[aria-label='Show My Screen Anyway']").toHaveCount(1);
    expect("button[aria-label='Stop Presenting']").toHaveCount(1);
});

test("the paused-stream panel is NOT shown on another participant's screen-share card", async () => {
    const { thread } = await setupPausedScreenShare();
    await mountScreenCardFor(thread, REMOTE_SESSION_ID);
    expect("h1:contains('You are Presenting')").toHaveCount(0);
    expect("button[aria-label='Stop Presenting']").toHaveCount(0);
});
