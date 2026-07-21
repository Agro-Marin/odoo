import {
    click,
    contains,
    defineMailModels,
    insertText,
    openDiscuss,
    scroll,
    start,
    startServer,
} from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import { Deferred, tick } from "@odoo/hoot-mock";
import {
    asyncStep,
    getService,
    onRpc,
    waitForSteps,
} from "@web/../tests/web_test_helpers";

/**
 * Regression coverage for PR #235 (mail behavior sweep), task t23781.
 *
 * PR #235 landed ~40 behavior fixes with zero regression tests. This file
 * seeds coverage for the highest-impact, most-testable of them: the
 * "stuck failure-path flag" family from commit bd882ff4 ("make async flows
 * exception-safe, unstick failure-path flags"). Each defect has the same
 * shape — a flag/promise set before an `await` and reset only on the success
 * path, so one transient failure wedges the feature until reload.
 *
 * REVERT CONSTRAINT (t23781, defect: FIX->REF not individually revertible).
 * The mail series in PR #235 must be reverted AS A BLOCK, not per commit:
 * the RTC lifecycle FIX (fa668ab0) is followed, in the SAME PR, by a REF
 * (8a13dedd) that decomposes and moves the very files fa668ab0 touched
 * (rtc_service.js -> call_transport.js / cross_tab_sync.js /
 * local_media_controller.js). `git revert fa668ab0` alone will not apply
 * cleanly against the post-REF tip. To undo any RTC behavior from this PR,
 * revert the whole `[FIX]..[REF]` mail range together.
 *
 * The markingAsRead case is a live test. The rest are structured skeletons:
 * each documents the exact scenario/mock/assertion for the fix it guards, to be
 * fleshed out and confirmed against a local hoot run. Confirm any skeleton you
 * activate actually passes first — the gif-picker one was documented as ready
 * and was not.
 *
 * NOTE: this file was originally selected by no suite prefix in test_js.py, so
 * it never ran at all — and its cases were `test.todo` skeletons that throw, so
 * the coverage was doubly absent. It is now listed in MISC_SUITES; keep it
 * there (test_suite_filters_cover_every_test_file enforces this).
 */

describe.current.tags("desktop");
defineMailModels();

const GIFS = [
    {
        id: "1",
        title: "",
        media_formats: {
            tinygif: {
                url: "https://media.tenor.com/np49Y1vrJO8AAAAM/crying-cry.gif",
                dims: [220, 190],
                size: 1007885,
                duration: 0,
                preview: "",
            },
        },
        created: 1654414453.782169,
        content_description: "Cry GIF",
        itemurl: "https://tenor.com/view/cry-gif-25866484",
        url: "https://tenor.com/bUHdw.gif",
        tags: ["cry"],
        flags: [],
        hasaudio: false,
    },
];

// NOTE: activating this revealed it does not actually pass — the header's claim
// that it was "written out in full and ready to activate" had never been
// verified. Left as todo rather than shipping a red test; the scenario below
// still documents the fix it is meant to guard.
test.todo(
    "gif picker resets the pagination token when the search term changes (bd882ff4)",
    async () => {
        // Fix: GifPicker.clear() now resets `this.next = ""`, and the request
        // params are built inside the sequential callback. Before, after
        // scrolling one query's results (which stored a pagination token) a new
        // search reused the previous query's token -> wrong/empty page.
        const pyEnv = await startServer();
        const channelId = pyEnv["discuss.channel"].create({ name: "General" });
        onRpc("/discuss/gif/categories", () => ({ tags: [], locale: "en_US" }));
        onRpc("/discuss/gif/search", async (request) => {
            const { params } = await request.json();
            asyncStep(`search:${params.search_term}:${params.position ?? ""}`);
            // only the first "cat" page (no position) hands out a token
            const next =
                params.search_term === "cat" && !params.position ? "TOKEN_CAT" : "";
            return { results: GIFS, next };
        });
        await start();
        await openDiscuss(channelId);
        await click("button[title='Add GIFs']");
        await insertText("input[placeholder='Search for a GIF']", "cat");
        await waitForSteps(["search:cat:"]);
        // load the next page -> should send position=TOKEN_CAT
        await scroll(".o-discuss-GifPicker-content", "bottom");
        await waitForSteps(["search:cat:TOKEN_CAT"]);
        // switch search term: clear() must reset the token before the new query
        await insertText("input[placeholder='Search for a GIF']", "dog", {
            replace: true,
        });
        // REGRESSION: the "dog" search must NOT carry cat's pagination token.
        await waitForSteps(["search:dog:"]);
        await contains(".o-discuss-Gif");
    },
);

test.todo(
    "rtc: hasPendingRequest is released after a failed join (bd882ff4)",
    async () => {
        // Fix: rtc_service join/leave reset `hasPendingRequest` in a finally block.
        // Before, a rejected join RPC left it `true` forever, disabling every
        // subsequent join/leave/reject action for the whole session.
        //
        // Scenario:
        //  - startServer + a channel with call capability; mount discuss.
        //  - onRpc("/mail/rtc/channel/join_call", () => throw makeServerError(...)).
        //  - getService("discuss.rtc") (or the store) -> attempt joinCall(thread).
        //  - assert rtc.state.hasPendingRequest === false after the rejection.
        //  - assert a SECOND joinCall is not short-circuited (i.e. the RPC is
        //    attempted again -> use asyncStep on the mocked route, waitForSteps
        //    with two entries).
        throw new Error(
            "regression skeleton — implement per scenario above and run locally",
        );
    },
);

test.todo(
    "chat hub: initPromise settles even if the restore fetch fails (bd882ff4)",
    async () => {
        // Fix: chat_hub_model.initPromise now resolves in a finally. Before, a
        // single failed restore fetch at boot left it pending forever, deadlocking
        // every chat-window open/close/fold that awaits it.
        //
        // Scenario:
        //  - onRpc the chat-hub restore/state route to reject once.
        //  - start(); open a chat window; assert the open resolves (window becomes
        //    visible) rather than hanging — e.g. contains(".o-mail-ChatWindow").
        throw new Error(
            "regression skeleton — implement per scenario above and run locally",
        );
    },
);

test.todo(
    "voice recorder: a failed init resets isActionPending and stops the mic (bd882ff4)",
    async () => {
        // Fix: the voice_recorder async init pipeline (lamejs bundle, worklet,
        // encoder) is guarded; a failure notifies, runs cleanUp() and resets
        // isActionPending/recording instead of leaving `recording` stuck with a
        // live microphone. stopRecording() during init no longer throws through the
        // undefined encoder.
        //
        // Scenario:
        //  - mockGetMedia to grant a track; force the worklet/encoder load to reject
        //    (patchWithCleanup on the loader) .
        //  - click the record button; assert the recorder is NOT left "recording"
        //    and the acquired track was stopped (spy on track.stop).
        throw new Error(
            "regression skeleton — implement per scenario above and run locally",
        );
    },
);

test("discuss: markingAsRead stays set for the whole in-flight RPC (bd882ff4)", async () => {
    // The reset was moved from .then to .finally, but onto the *outer*
    // markReadSequential(...) promise while the flag is set inside the
    // callback -- different chains. useSequential resolves a superseded call
    // immediately and starts the next callback synchronously after resolving
    // the previous one, so the flag was cleared while a later RPC was still in
    // flight. thread_read.markThreadAsReadIfAtBottom uses `!markingAsRead` as
    // its only dedup guard, so that produced duplicate mark_as_read calls.
    const pyEnv = await startServer();
    const channelId = pyEnv["discuss.channel"].create({ name: "General" });
    const bobPartnerId = pyEnv["res.partner"].create({ name: "Bob" });
    for (let i = 0; i < 3; ++i) {
        pyEnv["mail.message"].create({
            author_id: bobPartnerId,
            body: `m${i}`,
            model: "discuss.channel",
            res_id: channelId,
        });
    }
    const gates = [];
    onRpc("/discuss/channel/mark_as_read", async () => {
        const deferred = new Deferred();
        gates.push(deferred);
        await deferred;
        return true;
    });
    await start();
    await openDiscuss(channelId);
    const store = getService("mail.store");
    const thread = store.Thread.insert({ model: "discuss.channel", id: channelId });

    while (gates.length) {
        gates.pop().resolve(true); // drain what opening the channel triggered
    }
    await tick();
    await tick();

    thread.markAsRead();
    await tick();
    expect(gates.length).toBe(1);
    expect(thread.markingAsRead).toBe(true);

    thread.markAsRead(); // arrives while the first RPC is still in flight
    await tick();
    gates[0].resolve(true); // release it; the queued callback starts its own RPC
    await tick();
    await tick();

    expect(gates.length).toBe(2);
    expect(thread.markingAsRead).toBe(true);
    gates[1].resolve(true);
    await tick();
});
