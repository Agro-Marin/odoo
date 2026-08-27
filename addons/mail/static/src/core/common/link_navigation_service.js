/** @odoo-module native */
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { getOrigin } from "@web/core/utils/urls";

export class LinkNavigation {
    /** @type {import("models").Store} */
    store;
    /** @type {import("@web/env").OdooEnv} */
    env;

    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {import("models").Store} store
     */
    constructor(env, store) {
        this.env = env;
        this.store = store;
    }

    /**
     * @param {MouseEvent} ev
     * @param {import("models").Thread} [thread]
     * @returns {boolean}
     */
    handleClickOnLink(ev, thread) {
        // The body of an EMAIL message is rendered into a shadow root
        // (`message.js:168`, gated by `message.xml:113`) while the click
        // handler sits on the message root, in the light DOM. `ev.target` is
        // therefore retargeted to the shadow host and `closest("a")` answered
        // null for every link in an email body -- so none of the redirects
        // below ever fired, and a decorated `#channel` mention silently fell
        // through to a full page load. The composed path names the element
        // that was actually clicked.
        const target = /** @type {Element} */ (ev.composedPath?.()[0] ?? ev.target);
        const link = target.closest?.("a");
        if (!link) {
            return false;
        }
        const model = link.dataset.oeModel;
        const id = Number(link.dataset.oeId);
        if (link.classList.contains("o_channel_redirect") && model && id) {
            ev.preventDefault();
            this.store.Thread.getOrFetch({ model, id }).then((thread) => {
                if (thread) {
                    thread.open({ focus: true });
                } else {
                    this.env.services.notification.add(
                        _t("This thread is no longer available."),
                        { type: "danger" },
                    );
                }
            });
            return true;
        } else if (link.classList.contains("o_mail_redirect") && id) {
            ev.preventDefault();
            this.onClickPartnerMention(ev, id);
            return true;
        } else if (link.classList.contains("o_message_redirect")) {
            const message = this.store["mail.message"].get(id);
            const targetThread = message?.thread;
            const showAccessError = () =>
                this.env.services.notification.add(
                    _t("This conversation isn’t available."),
                    { type: "danger" },
                );
            if (targetThread) {
                targetThread.checkReadAccess().then((hasAccess) => {
                    if (hasAccess) {
                        targetThread.highlightMessage = message;
                        let isOpen = targetThread.eq(thread);
                        if (!isOpen) {
                            isOpen = targetThread.open({
                                focus: true,
                                swapOpened: false,
                            });
                        }
                        if (!isOpen) {
                            window.open(link.href);
                        }
                    } else {
                        if (this.store.self_partner) {
                            showAccessError();
                        } else {
                            window.open(link.href);
                        }
                    }
                });
                ev.preventDefault();
                return true;
            } else if (
                link.href &&
                new URL(link.href, getOrigin()).origin === getOrigin()
            ) {
                showAccessError();
                ev.preventDefault();
                return true;
            }
        } else if (
            this.env.services.ui.isSmall &&
            ev.target.closest(".o-mail-ChatWindow") &&
            link.href &&
            !link.href.startsWith("#")
        ) {
            let url;
            try {
                url = new URL(link.href);
            } catch {
                return false;
            }
            if (
                browser.location.host === url.host &&
                browser.location.pathname.startsWith("/odoo")
            ) {
                this.store.ChatWindow.get({ thread })?.fold();
            }
        }
        return false;
    }

    /**
     * @param {MouseEvent} ev
     * @param {number} id
     */
    onClickPartnerMention(ev, id) {}

    /** @param {import("models").Thread} fromThread */
    onLinkFollowed(fromThread) {}
}

export const linkNavigationService = {
    dependencies: ["mail.store"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ "mail.store": any }} services
     * @returns {LinkNavigation}
     */
    start(env, services) {
        return new LinkNavigation(env, services["mail.store"]);
    },
};

registry.category("services").add("mail.link_navigation", linkNavigationService);
