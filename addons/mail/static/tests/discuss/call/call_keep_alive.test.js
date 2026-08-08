import {
    click,
    contains,
    defineMailModels,
    mockGetMedia,
    openDiscuss,
    start,
    startServer,
} from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";

describe.current.tags("desktop");
defineMailModels();

/**
 * The call keep-alive belongs to the call, not to the page.
 *
 * `_stopPing()` was called from `clear()` (per call) while the interval was
 * created inline in `start()` (per page), and `joinCall()` called a
 * `_startPing()` that did not exist. So joining a call threw a TypeError -- which
 * also skipped the rest of `joinCall` -- and once a user left their first call
 * the interval was cleared for the life of the page, leaving every later call
 * without the recovery pass for connections that never started.
 */
test("joining a call starts the keep-alive, leaving it stops it", async () => {
    const pyEnv = await startServer();
    const channelId = pyEnv["discuss.channel"].create({ name: "General" });
    mockGetMedia();
    const env = await start();
    const rtc = env.services["discuss.rtc"];
    await openDiscuss(channelId);

    expect(rtc._pingIntervalId).toBe(undefined, {
        message: "no call yet, so nothing to keep alive",
    });

    await click("[title='Start Call']");
    await contains(".o-discuss-CallActionList");
    expect(rtc._pingIntervalId).not.toBe(undefined, {
        message: "joining a call must arm the keep-alive",
    });

    await click(".o-discuss-CallActionList button[title='Disconnect']");
    await contains(".o-discuss-CallActionList", { count: 0 });
    expect(rtc._pingIntervalId).toBe(undefined, {
        message: "leaving the call must disarm it",
    });
});

test("re-joining a call does not leak the previous keep-alive", async () => {
    const pyEnv = await startServer();
    const channelId = pyEnv["discuss.channel"].create({ name: "General" });
    mockGetMedia();
    const env = await start();
    const rtc = env.services["discuss.rtc"];
    await openDiscuss(channelId);

    await click("[title='Start Call']");
    await contains(".o-discuss-CallActionList");
    const first = rtc._pingIntervalId;
    // A second join without an intervening leave must replace the interval, not
    // add a second one running forever against the same session.
    rtc._startPing();
    expect(rtc._pingIntervalId).not.toBe(first, {
        message: "_startPing must replace the running interval",
    });

    await click(".o-discuss-CallActionList button[title='Disconnect']");
    await contains(".o-discuss-CallActionList", { count: 0 });
    expect(rtc._pingIntervalId).toBe(undefined, {
        message: "a single stop must clear whatever _startPing armed",
    });
});
