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
