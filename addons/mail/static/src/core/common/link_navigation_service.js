// @ts-check
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
        const target = /** @type {Element} */ (ev.composedPath?.()[0] ?? ev.target);
        const link = target.closest?.("a");
        if (!link) {
            return false;
        }
        const model = link.dataset.oeModel;
        const id = Number(link.dataset.oeId);
        if (link.classList.contains("o_channel_redirect") && model && id) {
            ev.preventDefault();
            this.openRedirectedThread(model, id);
            return true;
        }
        if (link.classList.contains("o_mail_redirect") && id) {
            ev.preventDefault();
            this.onClickPartnerMention(ev, id);
            return true;
        }
        if (link.classList.contains("o_message_redirect")) {
            return this.openRedirectedMessage(ev, link, id, thread);
        }
        if (
            this.env.services.ui.isSmall &&
            /** @type {Element} */ (ev.target).closest(".o-mail-ChatWindow") &&
            link.href &&
            !link.href.startsWith("#")
        ) {
            this.foldChatWindowForInternalLink(link, thread);
        }
        return false;
    }

    /**
     * @param {string} model
     * @param {number} id
     */
    openRedirectedThread(model, id) {
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
    }

    /**
     * @param {MouseEvent} ev
     * @param {HTMLAnchorElement} link
     * @param {number} id
     * @param {import("models").Thread} [thread]
     * @returns {boolean}
     */
    openRedirectedMessage(ev, link, id, thread) {
        const message = this.store["mail.message"].get(id);
        const targetThread = message?.thread;
        if (targetThread) {
            targetThread
                .checkReadAccess()
                .then((hasAccess) =>
                    hasAccess
                        ? this.revealMessage(message, targetThread, link, thread)
                        : this.refuseMessage(link),
                );
            ev.preventDefault();
            return true;
        }
        if (link.href && new URL(link.href, getOrigin()).origin === getOrigin()) {
            this.notifyConversationUnavailable();
            ev.preventDefault();
            return true;
        }
        return false;
    }

    /**
     * @param {import("models").Message} message
     * @param {import("models").Thread} targetThread
     * @param {HTMLAnchorElement} link
     * @param {import("models").Thread} [thread]
     */
    revealMessage(message, targetThread, link, thread) {
        targetThread.highlightMessage = message;
        let isOpen = targetThread.eq(thread);
        if (!isOpen) {
            isOpen = targetThread.open({ focus: true, swapOpened: false });
        }
        if (!isOpen) {
            window.open(link.href);
        }
    }

    /** @param {HTMLAnchorElement} link */
    refuseMessage(link) {
        if (this.store.self_partner) {
            this.notifyConversationUnavailable();
        } else {
            window.open(link.href);
        }
    }

    notifyConversationUnavailable() {
        this.env.services.notification.add(_t("This conversation isn’t available."), {
            type: "danger",
        });
    }

    /**
     * @param {HTMLAnchorElement} link
     * @param {import("models").Thread} [thread]
     */
    foldChatWindowForInternalLink(link, thread) {
        let url;
        try {
            url = new URL(link.href);
        } catch {
            return;
        }
        if (
            browser.location.host === url.host &&
            browser.location.pathname.startsWith("/odoo")
        ) {
            this.store.ChatWindow.get({ thread })?.fold();
        }
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
