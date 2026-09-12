// @ts-check
/** @odoo-module native */
import { browser } from "@web/core/browser/browser";
import { makeLogger } from "@web/core/debug/debug_logger";
import { Deferred, Mutex } from "@web/core/utils/concurrency";

import { fields, Record } from "./record.js";
export const CHAT_HUB_KEY = "mail.ChatHub";
export const CHAT_HUB_COMPACT_LS = "mail.user_setting.chathub_compact";

const log = makeLogger("mail.chat_hub");

export class ChatHub extends Record {
    BUBBLE = 56;
    BUBBLE_START = 15;
    BUBBLE_LIMIT = 7;
    BUBBLE_OUTER = 10;
    WINDOW_GAP = 10;
    WINDOW_INBETWEEN = 5;
    WINDOW = 380;

    /**
     * @template {typeof Record} T
     * @this {T}
     * @param {import("@mail/model/record").RecordData} data
     * @param {import("@mail/model/record").RecordData} ids
     * @returns {InstanceType<T>}
     */
    static new(data, ids) {
        /** @type {import("models").ChatHub} */
        const chatHub = /** @type {import("models").ChatHub} */ (
            /** @type {unknown} */ (super.new(data, ids))
        );
        chatHub._onStorage = /** @param {StorageEvent} ev */ (ev) => {
            log.pipeline("crosstab storage", () => ({ key: ev.key }));
            if (ev.key === CHAT_HUB_KEY) {
                chatHub.load(ev.newValue || undefined).catch(() => {});
            } else if (ev.key === null) {
                chatHub.load().catch(() => {});
            }
            if (ev.key === CHAT_HUB_COMPACT_LS) {
                chatHub._recomputeCompact++;
            }
        };
        browser.addEventListener("storage", chatHub._onStorage);
        const endInit = log.perf("init");
        chatHub
            .load(browser.localStorage.getItem(CHAT_HUB_KEY) ?? undefined)
            .catch(() => {})
            .finally(() => {
                endInit({
                    opened: chatHub.opened.length,
                    folded: chatHub.folded.length,
                });
                chatHub.initPromise.resolve();
            });
        return /** @type {InstanceType<T>} */ (/** @type {unknown} */ (chatHub));
    }

    delete() {
        browser.removeEventListener("storage", this._onStorage);
        super.delete();
    }
    /** @type {(event: StorageEvent) => void} */
    _onStorage;
    _recomputeCompact = 0;
    compact = fields.Attr(false, {
        /** @this {import("models").ChatHub} */
        compute() {
            void this._recomputeCompact;
            return browser.localStorage.getItem(CHAT_HUB_COMPACT_LS) === "true";
        },
    });
    canShowOpened = fields.Many("ChatWindow");
    canShowFolded = fields.Many("ChatWindow");
    opened = fields.Many("ChatWindow", {
        inverse: "hubAsOpened",
        /** @this {import("models").ChatHub} */
        onAdd(r) {
            this.onRecompute();
        },
    });
    folded = fields.Many("ChatWindow", { inverse: "hubAsFolded" });
    initPromise = new Deferred();
    preFirstFetchPromise = new Deferred();
    loadMutex = new Mutex();

    async closeAll() {
        log.logic("closeAll", () => ({
            opened: this.opened.length,
            folded: this.folded.length,
        }));
        await this.initPromise;
        const promises = [];
        for (const cw of [...this.opened, ...this.folded]) {
            promises.push(cw.close({ notifyState: false }));
        }
        await Promise.all(promises);
        this.save();
    }

    hideAll() {
        log.logic("hideAll", () => ({ opened: this.opened.length }));
        for (const cw of this.opened) {
            cw.bypassCompact = false;
        }
        browser.localStorage.setItem(CHAT_HUB_COMPACT_LS, String(true));
        this._recomputeCompact++;
    }

    onRecompute() {
        if (this.opened.length > this.maxOpened) {
            log.logic("onRecompute folds overflow", () => ({
                opened: this.opened.length,
                maxOpened: this.maxOpened,
            }));
        }
        while (this.opened.length > this.maxOpened) {
            const cw = this.opened.pop();
            this.folded.unshift(cw);
        }
    }

    /** @param {string} [str="{}"] */
    async load(str = "{}") {
        await this.loadMutex.exec(() => this._load(str));
    }

    /** @param {string} str */
    async _load(str) {
        /** @type {{ opened?: Object[], folded?: Object[] }} */
        let parsed;
        log.lifecycle("load", () => ({ raw: str }));
        try {
            parsed = str && str !== "undefined" ? JSON.parse(str) : {};
        } catch {
            parsed = {};
        }
        const { opened = [], folded = [] } = parsed;
        const hasInvalidData =
            opened.some((data) => !data.id || !data.model) ||
            folded.some((data) => !data.id || !data.model);
        if (hasInvalidData) {
            log.logic("load discards invalid data");
            opened.length = 0;
            folded.length = 0;
            browser.localStorage.removeItem(CHAT_HUB_KEY);
        }
        /** @param {{id: number, model: string}} data */
        const getThread = (data) =>
            this.store.Thread.getOrFetch(data, ["display_name"]);
        const openPromises = opened.map(getThread);
        const foldPromises = folded.map(getThread);
        this.preFirstFetchPromise.resolve();
        const foldThreads = await Promise.all(foldPromises);
        const openThreads = await Promise.all(openPromises);
        /** @param {import("models").Thread[]} threads */
        const insertChatWindows = (threads) =>
            threads
                .filter((thread) => thread?.isChannelKind)
                .map((thread) => this.store.ChatWindow.insert({ thread }));
        const toFold = insertChatWindows(foldThreads);
        const toOpen = insertChatWindows(openThreads);
        log.pipeline("load resolved", () => ({
            requestedOpened: opened.length,
            requestedFolded: folded.length,
            toOpen: toOpen.length,
            toFold: toFold.length,
        }));
        for (const chatWindow of [...this.opened, ...this.folded]) {
            if (chatWindow.notIn(toOpen) && chatWindow.notIn(toFold)) {
                chatWindow.close({ notifyState: false });
            }
        }
        this.folded = /** @type {typeof this.folded} */ (
            /** @type {unknown} */ (toFold)
        );
        this.opened = /** @type {typeof this.opened} */ (
            /** @type {unknown} */ (toOpen)
        );
    }

    get maxOpened() {
        const chatBubblesWidth =
            this.BUBBLE_START + this.BUBBLE + this.BUBBLE_OUTER * 2;
        const startGap = this.store.env.services.ui.isSmall ? 0 : this.WINDOW_GAP;
        const endGap = this.store.env.services.ui.isSmall ? 0 : this.WINDOW_GAP;
        const available = browser.innerWidth - startGap - endGap - chatBubblesWidth;
        const maxAmountWithoutHidden = Math.max(
            1,
            Math.floor(available / (this.WINDOW + this.WINDOW_INBETWEEN)),
        );
        return maxAmountWithoutHidden;
    }

    get maxFolded() {
        const chatBubbleSpace = this.BUBBLE_START + this.BUBBLE + this.BUBBLE_OUTER * 2;
        return Math.min(
            this.BUBBLE_LIMIT,
            Math.floor(browser.innerHeight / chatBubbleSpace),
        );
    }

    save() {
        log.lifecycle("save", () => ({
            opened: this.opened.length,
            folded: this.folded.length,
        }));
        browser.localStorage.setItem(
            CHAT_HUB_KEY,
            JSON.stringify({
                opened: this.opened.map((cw) => ({
                    id: cw.thread.id,
                    model: cw.thread.model,
                })),
                folded: this.folded.map((cw) => ({
                    id: cw.thread.id,
                    model: cw.thread.model,
                })),
            }),
        );
    }

    showConversations = fields.Attr(false, {
        /** @this {import("models").ChatHub} */
        compute() {
            return this.canShowOpened.length + this.canShowFolded.length > 0;
        },
    });
}

ChatHub.register();
