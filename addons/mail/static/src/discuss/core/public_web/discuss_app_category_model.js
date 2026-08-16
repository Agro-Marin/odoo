/** @odoo-module native */
import { fields, Record } from "@mail/core/common/record";
import { compareDatetime } from "@mail/utils/common/misc";
import { browser } from "@web/core/browser/browser";
export class DiscussAppCategory extends Record {
    static id = "id";

    /**
     * @param {import("models").Thread} t1
     * @param {import("models").Thread} t2
     */
    sortThreads(t1, t2) {
        if (this.id === "channels") {
            return (t1.name || "").localeCompare(t2.name || "");
        }
        if (this.id === "chats") {
            return (
                compareDatetime(t2.lastInterestDt, t1.lastInterestDt) || t2.id - t1.id
            );
        }
        return t2.id - t1.id;
    }

    get isVisible() {
        return (
            !this.hidden &&
            (!this.hideWhenEmpty ||
                this.threads.some(
                    (thread) => thread.displayToSelf || thread.isLocallyPinned,
                ))
        );
    }

    /** @type {string} */
    extraClass;
    /** @type {string} */
    icon;
    /** @type {string} */
    id;
    /** @type {string} */
    name;
    hidden = fields.Attr(undefined, {
        /** @this {import("models").DiscussAppCategory} */
        compute() {
            return Boolean(
                localStorage.getItem(`mail.sidebar_category_${this.id}_hidden`),
            );
        },
        /** @this {import("models").DiscussAppCategory} */
        onUpdate() {
            const key = `mail.sidebar_category_${this.id}_hidden`;
            if (!this.hidden && this.hidden !== undefined) {
                if (localStorage.getItem(key) !== null) {
                    localStorage.removeItem(key);
                }
            } else {
                localStorage.setItem(key, true);
            }
        },
    });
    hideWhenEmpty = false;
    canView = false;
    app = fields.One("DiscussApp", {
        /** @this {import("models").DiscussAppCategory} */
        compute() {
            return this.store.discuss;
        },
    });
    _openLocally = false;
    localStateKey = fields.Attr(null, {
        /** @this {import("models").DiscussAppCategory} */
        compute() {
            if (this.saveStateToServer) {
                return null;
            }
            return `discuss_sidebar_category_${this.id}_open`;
        },
        /** @this {import("models").DiscussAppCategory} */
        onUpdate() {
            if (this.localStateKey) {
                const raw = browser.localStorage.getItem(this.localStateKey) ?? "true";
                try {
                    this._openLocally = raw === "undefined" ? true : JSON.parse(raw);
                } catch {
                    this._openLocally = true;
                }
            }
        },
    });
    /** @type {number} */
    sequence;

    get open() {
        return this.saveStateToServer
            ? this.store.settings[this.serverStateKey]
            : this._openLocally;
    }

    get saveStateToServer() {
        return (
            this.serverStateKey &&
            this.store.self_partner?.main_user_id?.share === false
        );
    }

    /** @param {boolean} value */
    set open(value) {
        if (this.saveStateToServer) {
            this.store.settings[this.serverStateKey] = value;
            this.store.env.services.orm.call(
                "res.users.settings",
                "set_res_users_settings",
                [[this.store.settings.id]],
                {
                    new_settings: {
                        [this.serverStateKey]: value,
                    },
                },
            );
        } else {
            this._openLocally = value;
            browser.localStorage.setItem(this.localStateKey, value);
        }
    }

    /** @param {boolean} value */
    applyBroadcastedOpen(value) {
        if (this.saveStateToServer) {
            this.store.settings[this.serverStateKey] = value;
        } else {
            this._openLocally = value;
        }
    }

    /** @type {string} */
    serverStateKey;
    threads = fields.Many("Thread", {
        /** @this {import("models").DiscussAppCategory} */
        sort(t1, t2) {
            return this.sortThreads(t1, t2);
        },
        inverse: "discussAppCategory",
    });
    threadsWithCounter = fields.Many("Thread", {
        inverse: "categoryAsThreadWithCounter",
    });
}

DiscussAppCategory.register();
