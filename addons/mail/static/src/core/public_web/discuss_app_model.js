// @ts-check
/** @odoo-module native */
import { fields, Record } from "@mail/core/common/record";
import {
    readLocalStorageItem,
    removeLocalStorageItem,
    setLocalStorageItem,
} from "@mail/utils/common/local_storage";
import { makeLogger } from "@web/core/debug/debug_logger";

const log = makeLogger("mail.discuss");
export const NO_MEMBERS_DEFAULT_OPEN_LS = "mail.user_setting.no_members_default_open";
export const DISCUSS_SIDEBAR_COMPACT_LS = "mail.user_setting.discuss_sidebar_compact";
export const LAST_DISCUSS_ACTIVE_ID_LS = "mail.user_setting.discuss_last_active_id";

export class DiscussApp extends Record {
    INSPECTOR_WIDTH = 300;
    COMPACT_SIDEBAR_WIDTH = 60;
    /** @type {'notification'|'channel'|'chat'|'livechat'|'inbox'|'starred'} */
    activeTab = "notification";
    searchTerm = "";
    isActive = false;
    isMemberPanelOpenByDefault = fields.Attr(true, {
        /** @this {import("models").DiscussApp} */
        compute() {
            return (
                readLocalStorageItem(this.store, NO_MEMBERS_DEFAULT_OPEN_LS) !== "true"
            );
        },
    });
    isSidebarCompact = fields.Attr(false, {
        /** @this {import("models").DiscussApp} */
        compute() {
            return (
                readLocalStorageItem(this.store, DISCUSS_SIDEBAR_COMPACT_LS) === "true"
            );
        },
    });
    lastActiveId = fields.Attr(undefined, {
        /** @this {import("models").DiscussApp} */
        compute() {
            return (
                readLocalStorageItem(this.store, LAST_DISCUSS_ACTIVE_ID_LS) ?? undefined
            );
        },
        /** @this {import("models").DiscussApp} */
        onUpdate() {
            if (this.lastActiveId) {
                setLocalStorageItem(
                    this.store,
                    LAST_DISCUSS_ACTIVE_ID_LS,
                    this.lastActiveId,
                );
            } else {
                removeLocalStorageItem(this.store, LAST_DISCUSS_ACTIVE_ID_LS);
            }
        },
    });
    thread = fields.One("Thread", {
        /** @this {import("models").DiscussApp} */
        onUpdate() {
            this._threadOnUpdate();
        },
    });
    hasRestoredThread = false;

    /** @param {import("@mail/core/common/action").Action} [nextActiveAction] */
    shouldDisableMemberPanelAutoOpenFromClose(nextActiveAction) {
        return true;
    }

    _threadOnUpdate() {
        this.lastActiveId = this.store.Thread.localIdToActiveId(this.thread?.localId);
        log.logic("thread updated", () => ({
            thread: this.thread?.localId,
            lastActiveId: this.lastActiveId,
        }));
    }
}

DiscussApp.register();
