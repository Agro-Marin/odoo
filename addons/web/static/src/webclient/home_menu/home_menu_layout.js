// @ts-check
/** @odoo-module native */

import { user } from "@web/core/user";
import { Mutex } from "@web/core/utils/concurrency";
import { session } from "@web/session";
import {
    parseHomeMenuConfig,
    serializeHomeMenuConfig,
} from "@web/webclient/menus/menu_utils";

/**
 * The launcher's layout: which apps are pinned, which are hidden, what order
 * they sit in, and where that is written down. The grid itself only reads it.
 *
 * Its own writer, and the reason it is an object rather than a handful of
 * methods on the component: `res.users.settings` writes are not serialised,
 * so two pins in quick succession put two whole layouts in flight at once —
 * `{pinned:[a]}` and `{pinned:[a,b]}` — and whichever reaches the server last
 * wins. The second pin is then lost with nothing to show for it.
 *
 * Every write goes through one mutex, so a later layout can never be overtaken
 * by an earlier one, and a write serialises the layout when its turn comes
 * rather than when it was asked for. That second part makes the queued writes
 * redundant with each other, so all but the first are dropped: tidying a
 * launcher with six clicks is one request carrying the finished layout, not
 * six carrying six prefixes of it.
 */
/**
 * The apps a layout shows: everything it does not hide. An app the layout
 * cannot name is always shown, since nothing can have hidden it.
 *
 * @template {{ xmlid?: string }} T
 * @param {import("@web/webclient/menus/menu_utils").HomeMenuConfig} config
 * @param {T[]} apps
 * @returns {T[]}
 */
export function shownApps(config, apps) {
    return apps.filter(
        (app) => app.xmlid === undefined || !config.hidden.includes(app.xmlid),
    );
}

/**
 * The pinned ones among `apps`, in the order they were pinned rather than the
 * order they arrived in. An xmlid pinned but absent — an app uninstalled since
 * — is skipped rather than left as a hole.
 *
 * @template {{ xmlid?: string }} T
 * @param {import("@web/webclient/menus/menu_utils").HomeMenuConfig} config
 * @param {T[]} apps
 * @returns {T[]}
 */
export function pinnedApps(config, apps) {
    const byXmlid = new Map(
        apps.flatMap((app) => (app.xmlid === undefined ? [] : [[app.xmlid, app]])),
    );
    return config.pinned.flatMap((xmlid) => {
        const app = byXmlid.get(xmlid);
        return app ? [app] : [];
    });
}

/**
 * The stored order after a drag: `movedId` lifted out and put back after
 * `afterId`, or at the front when it was dropped before everything.
 *
 * Answers `null` rather than an order when `movedId` is not in the list. That
 * is the case `Array.indexOf` reports as -1 and `splice(-1, 1)` then acts on
 * by removing the LAST app instead, silently reordering something the user
 * never touched.
 *
 * An `afterId` that is not in the list lands at the front, which is where the
 * same -1 put it before, and is the only sensible answer for "after an app
 * that is not here".
 *
 * @param {string[]} order the stored order, unchanged by this
 * @param {string} movedId
 * @param {string} [afterId] the app it was dropped behind, if any
 * @returns {string[] | null}
 */
export function orderAfterDrag(order, movedId, afterId) {
    const from = order.indexOf(movedId);
    if (from === -1) {
        return null;
    }
    const next = [...order];
    next.splice(from, 1);
    next.splice(afterId ? next.indexOf(afterId) + 1 : 0, 0, movedId);
    return next;
}

export class HomeMenuLayout {
    /** @type {import("@web/webclient/menus/menu_utils").HomeMenuConfig} */
    config;
    /**
     * What this user falls back to, their company's or the empty layout. Held
     * rather than derived: publishing the current layout as the company's
     * moves it, and a getter minting a fresh object per call would move a copy
     * nobody reads.
     *
     * @type {import("@web/webclient/menus/menu_utils").HomeMenuConfig}
     */
    defaultConfig;

    /**
     * @param {{
     *  config: import("@web/webclient/menus/menu_utils").HomeMenuConfig,
     *  defaultConfig: import("@web/webclient/menus/menu_utils").HomeMenuConfig,
     *  orm: import("services").ServiceFactories["orm"],
     * }} params
     */
    constructor({ config, defaultConfig, orm }) {
        this.config = config;
        this.defaultConfig = defaultConfig;
        this.orm = orm;
        this.mutex = new Mutex();
        /** Whether a change is waiting to be written. */
        this.unsaved = false;
    }

    /** @param {import("@web/webclient/menus/menu_utils").HomeMenuConfig} config */
    setConfig(config) {
        this.config = config;
    }

    /** @param {{ xmlid?: string }} app */
    isPinned(app) {
        return app.xmlid !== undefined && this.config.pinned.includes(app.xmlid);
    }

    /** @param {{ xmlid?: string }} app */
    isHidden(app) {
        return app.xmlid !== undefined && this.config.hidden.includes(app.xmlid);
    }

    /** @returns {boolean} */
    get isCustomised() {
        return (
            serializeHomeMenuConfig(this.config) !==
            serializeHomeMenuConfig(this.defaultConfig)
        );
    }

    /** @returns {boolean} */
    get canSetCompanyDefault() {
        return user.isAdmin;
    }

    /** @param {{ xmlid?: string }} app */
    togglePinned(app) {
        if (app.xmlid === undefined) {
            return;
        }
        const index = this.config.pinned.indexOf(app.xmlid);
        if (index === -1) {
            this.config.pinned.push(app.xmlid);
        } else {
            this.config.pinned.splice(index, 1);
        }
        return this.persist();
    }

    /** @param {{ xmlid?: string }} app */
    toggleHidden(app) {
        if (app.xmlid === undefined) {
            return;
        }
        const index = this.config.hidden.indexOf(app.xmlid);
        if (index === -1) {
            this.config.hidden.push(app.xmlid);
            const pinnedIndex = this.config.pinned.indexOf(app.xmlid);
            if (pinnedIndex !== -1) {
                this.config.pinned.splice(pinnedIndex, 1);
            }
        } else {
            this.config.hidden.splice(index, 1);
        }
        return this.persist();
    }

    /** @param {string[]} order */
    setOrder(order) {
        this.config.order = order;
        return this.persist();
    }

    /**
     * @returns {{ order: string[], saved: Promise<unknown> }}
     */
    reset() {
        const defaults = this.defaultConfig;
        this.config.order = [...defaults.order];
        this.config.pinned = [...defaults.pinned];
        this.config.hidden = [...defaults.hidden];
        return {
            order: defaults.order,
            saved: this.mutex.exec(() => user.setUserSettings("homemenu_config", null)),
        };
    }

    async setCompanyDefault() {
        const config = JSON.parse(serializeHomeMenuConfig(this.config));
        await this.orm.write("res.company", [user.activeCompany.id], {
            homemenu_default_config: config,
        });
        session.homemenu_default_config = config;
        this.defaultConfig = parseHomeMenuConfig(config);
    }

    persist() {
        this.unsaved = true;
        return this.mutex.exec(() => {
            if (!this.unsaved) {
                return;
            }
            this.unsaved = false;
            return user.setUserSettings(
                "homemenu_config",
                serializeHomeMenuConfig(this.config),
            );
        });
    }
}
