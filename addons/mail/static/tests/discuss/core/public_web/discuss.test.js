import { waitUntilSubscribe } from "@bus/../tests/bus_test_helpers";
import {
    contains,
    defineMailModels,
    openDiscuss,
    start,
    startServer,
} from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import { EventBus } from "@odoo/owl";
import {
    Command,
    mockService,
    patchWithCleanup,
    withUser,
} from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { rpc } from "@web/core/network";

describe.current.tags("desktop");
defineMailModels();

test("open channel in discuss from push notification", async () => {
    patchWithCleanup(window.navigator, {
        serviceWorker: Object.assign(new EventBus(), {
            register: () => Promise.resolve(),
            ready: Promise.resolve(),
        }),
    });
    const pyEnv = await startServer();
    const channelId = pyEnv["discuss.channel"].create({ name: "General" });
    await start();
    await openDiscuss("mail.box_inbox");
    await contains(".o-mail-DiscussContent-threadName[title='Inbox']");
    browser.navigator.serviceWorker.dispatchEvent(
        new MessageEvent("message", {
            data: { action: "OPEN_CHANNEL", data: { id: channelId } },
        }),
    );
    await contains(".o-mail-DiscussContent-threadName[title='General']");
});

test("notify message to user as non member", async () => {
    // `browser`, not `window`: the `browser` facade is the seam the mail code
    // reads notification permission through (@see out_of_focus_service,
    // webclient, notification_permission_service), and `browser.Notification`
    // snapshots `window.Notification` at module load, so patching the raw
    // global no longer reaches it. Consistent with messaging_menu.test.js.
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
    // `waitForSteps`: the notification is emitted from an async chain
    // (`getRegistration()` -> `pushManager.getSubscription()` -> `isOnMainTab()`)
    // that is not ordered against the message reaching the DOM, so a synchronous
    // `verifySteps` here was checking at an arbitrary point in that chain.
    await expect.waitForSteps(["push notification"]);
});
