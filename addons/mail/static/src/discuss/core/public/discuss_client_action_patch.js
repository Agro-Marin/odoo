// @ts-check
/** @odoo-module native */
import { DiscussClientAction } from "@mail/core/public_web/discuss_client_action";
import { WelcomePage } from "@mail/discuss/core/public/welcome_page";
import { useExternalListener } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { makeLogger } from "@web/core/debug/debug_logger";
import { patch } from "@web/core/utils/patch";

const log = makeLogger("mail.discuss.public");
DiscussClientAction.components = { ...DiscussClientAction.components, WelcomePage };
patch(DiscussClientAction.prototype, {
    setup() {
        super.setup();
        if (this.store.isChannelTokenSecret) {
            browser.history.replaceState(
                browser.history.state,
                null,
                `/discuss/channel/${this.store.discuss.thread.id}${browser.location.search}`,
            );
        }
        const url = new URL(browser.location.href);
        url.searchParams.delete("email_token");
        browser.history.replaceState(browser.history.state, null, url.toString());
        useExternalListener(browser, "popstate", () =>
            this.restoreDiscussThread(this.props),
        );
    },
    getActiveId() {
        const currentURL = new URL(browser.location.href);
        if (!/\/discuss\/channel\/\d+$/.test(currentURL.pathname)) {
            return (
                this.store.Thread.localIdToActiveId(
                    this.store.discuss.thread?.localId,
                ) ?? null
            );
        }
        return `discuss.channel_${currentURL.pathname.split("/")[3]}`;
    },
    async restoreDiscussThread() {
        await super.restoreDiscussThread(...arguments);
        this.store.is_welcome_page_displayed ||=
            this.store.discuss.thread?.default_display_mode === "video_full_screen";
        log.lifecycle("public restore", () => ({
            thread: this.store.discuss.thread?.localId,
            welcomePage: this.store.is_welcome_page_displayed,
        }));
    },
    closeWelcomePage() {
        log.lifecycle("closeWelcomePage");
        this.store.is_welcome_page_displayed = false;
    },
});
