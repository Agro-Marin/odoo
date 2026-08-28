import { waitUntilSubscribe } from "@bus/../tests/bus_test_helpers";
import {
    contains,
    defineMailModels,
    openDiscuss,
    start,
    startServer,
} from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import {
    Command,
    mockService,
    mockServiceWorkerContainer,
    patchWithCleanup,
    withUser,
} from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { rpc } from "@web/core/network";

describe.current.tags("desktop");
defineMailModels();

test("open channel in discuss from push notification", async () => {
    const serviceWorker = mockServiceWorkerContainer();
    const pyEnv = await startServer();
    const channelId = pyEnv["discuss.channel"].create({ name: "General" });
    await start();
    await openDiscuss("mail.box_inbox");
    await contains(".o-mail-DiscussContent-threadName[title='Inbox']");
    serviceWorker.dispatchEvent(
        new MessageEvent("message", {
            data: { action: "OPEN_CHANNEL", data: { id: channelId } },
        }),
    );
    await contains(".o-mail-DiscussContent-threadName[title='General']");
});

test("notify message to user as non member", async () => {
    patchWithCleanup(browser, {
        Notification: class Notification {
            static get permission() {
                return "granted";
            }
            constructor() {
                expect.step("push notification");
            }
            addEventListener() {}
        },
    });
    mockService("multi_tab", { isOnMainTab: () => true });
    const pyEnv = await startServer();
    const johnUser = pyEnv["res.users"].create({ name: "John" });
    const johnPartner = pyEnv["res.partner"].create({
        name: "John",
        user_ids: [johnUser],
    });
    const channelId = pyEnv["discuss.channel"].create({
        channel_type: "chat",
        channel_member_ids: [Command.create({ partner_id: johnPartner })],
    });
    await start();
    await Promise.all([
        openDiscuss(channelId),
        waitUntilSubscribe(`discuss.channel_${channelId}`),
    ]);
    await withUser(johnUser, () =>
        rpc("/mail/message/post", {
            post_data: { body: "Hello!", message_type: "comment" },
            thread_id: channelId,
            thread_model: "discuss.channel",
        }),
    );
    await contains(".o-mail-Message", { text: "Hello!" });
    await expect.waitForSteps(["push notification"]);
});

test("RTC logs pushed by the service worker are offered as a download", async () => {
    const serviceWorker = mockServiceWorkerContainer();
    await startServer();
    await start();
    await openDiscuss("mail.box_inbox");
    await contains(".o-mail-DiscussContent-threadName[title='Inbox']");

    /** @type {Blob[]} */
    const blobs = [];
    /** @type {string[]} */
    const revoked = [];
    const clicked = [];
    patchWithCleanup(URL, {
        createObjectURL(blob) {
            blobs.push(blob);
            return "blob:rtc-logs";
        },
        revokeObjectURL(url) {
            revoked.push(url);
        },
    });
    patchWithCleanup(HTMLAnchorElement.prototype, {
        click() {
            clicked.push({ download: this.download, href: this.href });
        },
    });
    serviceWorker.dispatchEvent(
        new MessageEvent("message", {
            data: { action: "POST_RTC_LOGS", data: { step: "connected" } },
        }),
    );
    await contains(".o-mail-DiscussContent-threadName[title='Inbox']");

    expect(clicked).toHaveLength(1);
    expect(clicked[0].download).toMatch(
        /^RtcLogs_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}\.json$/,
    );
    expect(clicked[0].href).toInclude("blob:rtc-logs");
    expect(revoked).toEqual(["blob:rtc-logs"]);
    expect(blobs).toHaveLength(1);
    expect(blobs[0].type).toBe("application/json");
    const logs = JSON.parse(await blobs[0].text());
    expect(logs.step).toBe("connected");
    expect(logs.odooInfo).toEqual(odoo.info);
});

test("RTC logs pushed with no payload still carry the version info", async () => {
    const serviceWorker = mockServiceWorkerContainer();
    await startServer();
    await start();
    await openDiscuss("mail.box_inbox");
    await contains(".o-mail-DiscussContent-threadName[title='Inbox']");

    /** @type {Blob[]} */
    const blobs = [];
    patchWithCleanup(URL, {
        createObjectURL(blob) {
            blobs.push(blob);
            return "blob:rtc-logs";
        },
        revokeObjectURL() {},
    });
    patchWithCleanup(HTMLAnchorElement.prototype, { click() {} });
    serviceWorker.dispatchEvent(
        new MessageEvent("message", {
            data: { action: "POST_RTC_LOGS", data: undefined },
        }),
    );
    await contains(".o-mail-DiscussContent-threadName[title='Inbox']");

    expect(blobs).toHaveLength(1);
    expect(JSON.parse(await blobs[0].text())).toEqual({ odooInfo: odoo.info });
});
