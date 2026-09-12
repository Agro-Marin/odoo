// @ts-check
/** @odoo-module native */
import { fields, Record } from "@mail/core/common/record";
import {
    readLocalStorageItem,
    removeLocalStorageItem,
    setLocalStorageItem,
} from "@mail/utils/common/local_storage";
import { compareDatetime } from "@mail/utils/common/misc";
import { makeLogger } from "@web/core/debug/debug_logger";

const log = makeLogger("mail.discuss.sidebar");
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
                compareDatetime(t2.lastInterestDt, t1.lastInterestDt) ||
                Number(t2.id) - Number(t1.id)
            );
        }
        return Number(t2.id) - Number(t1.id);
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
            return Boolean(readLocalStorageItem(this.store, this.hiddenStateKey));
        },
        /** @this {import("models").DiscussAppCategory} */
        onUpdate() {
            if (!this.hidden && this.hidden !== undefined) {
                if (readLocalStorageItem(this.store, this.hiddenStateKey) !== null) {
                    removeLocalStorageItem(this.store, this.hiddenStateKey);
                }
            } else {
                setLocalStorageItem(this.store, this.hiddenStateKey, String(true));
            }
        },
    });
    get hiddenStateKey() {
        return `mail.sidebar_category_${this.id}_hidden`;
    }
    hideWhenEmpty = false;
    canView = false;
    app = fields.One("DiscussApp", {
        /** @this {import("models").DiscussAppCategory} */
        compute() {
            return this.store.discuss;
        },
    });
    get localStateKey() {
        return `discuss_sidebar_category_${this.id}_open`;
    }
    /** @type {number} */
    sequence;

    get open() {
        if (this.saveStateToServer) {
            return this.store.settings[this.serverStateKey];
        }
        const raw = readLocalStorageItem(this.store, this.localStateKey) ?? "true";
        try {
            return raw === "undefined" ? true : Boolean(JSON.parse(raw));
        } catch {
            return true;
        }
    }

    get saveStateToServer() {
        return (
            this.serverStateKey &&
            this.store.self_partner?.main_user_id?.share === false
        );
    }

    /** @param {boolean} value */
    set open(value) {
        log.logic("category open", () => ({
            id: this.id,
            value,
            server: Boolean(this.saveStateToServer),
        }));
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
            setLocalStorageItem(this.store, this.localStateKey, String(value));
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
