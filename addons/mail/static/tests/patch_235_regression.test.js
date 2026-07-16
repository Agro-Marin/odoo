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
import { describe, test } from "@odoo/hoot";
import { asyncStep, onRpc, waitForSteps } from "@web/../tests/web_test_helpers";

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
 * The gif-picker case below is written out in full and ready to activate
 * (flip `test.todo` -> `test`). The remaining cases are structured skeletons:
 * each documents the exact scenario/mock/assertion for the fix it guards, to
 * be fleshed out and confirmed against a local hoot run (this suite could not
 * be executed in the authoring environment — CI is down per t23601).
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

test.todo(
    "discuss: markingAsRead resets after a non-404 failure (bd882ff4)",
    async () => {
        // Fix: thread_model_patch.markAsRead moved the `markingAsRead` reset from
        // .then to .finally. Before, a non-404 failure left it `true`, permanently
        // disabling auto-mark-as-read for that channel.
        //
        // Scenario:
        //  - open a channel with unread messages; onRpc the set_last_seen route to
        //    reject with a 500 once.
        //  - assert thread.markingAsRead === false afterwards, and that a later
        //    mark-as-read is attempted again.
        throw new Error(
            "regression skeleton — implement per scenario above and run locally",
        );
    },
);
