import {
    click,
    contains,
    defineMailModels,
    mockGetMedia,
    openDiscuss,
    start,
    startServer,
} from "@mail/../tests/mail_test_helpers";
import { beforeEach, describe, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";

describe.current.tags("desktop");
defineMailModels();

beforeEach(() => mockGetMedia());

test("joining a call on a browser without webRTC warns instead of joining", async () => {
    const pyEnv = await startServer();
    const channelId = pyEnv["discuss.channel"].create({ name: "General" });
    await start();
    await openDiscuss(channelId);
    patchWithCleanup(browser, { RTCPeerConnection: undefined });
    await click("[title='Start Call']");
    await contains(".o_notification:contains('Your browser does not support webRTC.')");
    await contains(".o-discuss-Call", { count: 0 });
});

test("joining a call on a browser without MediaStream warns instead of joining", async () => {
    const pyEnv = await startServer();
    const channelId = pyEnv["discuss.channel"].create({ name: "General" });
    await start();
    await openDiscuss(channelId);
    patchWithCleanup(browser, { MediaStream: undefined });
    await click("[title='Start Call']");
    await contains(".o_notification:contains('Your browser does not support webRTC.')");
    await contains(".o-discuss-Call", { count: 0 });
});
