/** @odoo-module native */
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { getOrigin } from "@web/core/utils/urls";

/**
 * Where a click inside message content goes.
 *
 * Message bodies are server-rendered HTML carrying `o_channel_redirect`,
 * `o_mail_redirect` and `o_message_redirect` anchors, so following one is a
 * decision about a DOM event, not about a record: read the anchor's dataset,
 * decide between opening a thread, popping an avatar card, highlighting a
 * message, or letting the browser navigate.
 *
 * That decision used to live on `Store` — ~95 lines of `ev.target.closest("a")`
 * on a reactive record in `recordByLocalId`, alongside the record registry, the
 * RPC batcher and the session identity. It reaches into the store constantly
 * (`Thread.getOrFetch`, `mail.message`, `ChatWindow`, `self_partner`), which is
 * what made it look like it belonged there; but it *consumes* the store rather
 * than being part of it, and nothing about a click handler wants to be a
 * reactive graph node.
 *
 * A class, not an object literal: the `web` layer extends this with the
 * backend-only "open the record's form view" branch, and a prototype is the seam
 * that lets it do so with `super` (@see tooling/architecture/js_service_shape).
 */
export class LinkNavigation {
    /** @type {import("models").Store} */
    store;
    /** @type {import("@web/env").OdooEnv} */
    env;

    constructor(env, store) {
        this.env = env;
        this.store = store;
    }

    /**
     * @param {MouseEvent} ev
     * @param {import("models").Thread} [thread] the thread the click happened in
     * @returns {boolean} whether the click was handled here
     */
    handleClickOnLink(ev, thread) {
        const link = ev.target.closest("a");
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
                // link.href (not the raw attribute): a relative
                // /mail/message/... href is same-origin by definition but a
                // raw-attribute startsWith(origin) check never matched it,
                // navigating away instead of showing the access error
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
                // Ignore invalid URLs
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
     * Neutral on the public page, where there is no avatar card to pop and no
     * popover service to pop it with. `discuss/core/web` supplies the backend
     * behaviour.
     *
     * @param {MouseEvent} ev
     * @param {number} id `res.partner` id
     */
    onClickPartnerMention(ev, id) {}

    /**
     * Called after a link has been followed away from `fromThread`. Neutral
     * here; the backend uses it to fold the chat window the click came from.
     *
     * @param {import("models").Thread} fromThread
     */
    onLinkFollowed(fromThread) {}
}

export const linkNavigationService = {
    // `notification` and `ui` are read lazily through `env.services` inside the
    // handler rather than declared here, which is how this code already behaved
    // on `Store`. Promoting them to hard dependencies would be tidier but is a
    // behaviour change at service-startup time on the public page, where the
    // set of started services differs -- a separate decision from moving the
    // code, and deliberately not bundled into it.
    dependencies: ["mail.store"],
    /** @returns {LinkNavigation} */
    start(env, services) {
        return new LinkNavigation(env, services["mail.store"]);
    },
};

registry.category("services").add("mail.link_navigation", linkNavigationService);
