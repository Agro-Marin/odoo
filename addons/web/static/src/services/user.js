// @ts-check
/** @odoo-module native */

import { EventBus } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { cookie } from "@web/core/browser/cookie";
import { UserEvent } from "@web/core/events";
import { pyToJsLocale } from "@web/core/l10n/utils";
import { rpc } from "@web/core/network/rpc";
import { ensureArray, sortBy } from "@web/core/utils/collections/arrays";
import { Cache } from "@web/core/utils/collections/cache";
import { session } from "@web/session";

/**
 * User identity, company context, group membership, and access-right checks.
 * Exports a singleton `user` object constructed from the session, along with
 * a `userBus` that emits `ACTIVE_COMPANIES_CHANGED` on company switches.
 * @module user
 */

/**
 * One entry of ``session_info``'s ``user_companies``.
 *
 * Shape is fixed by the server (see ``web/tests/test_session_info.py``):
 * ``allowed_companies`` carries id/name/sequence/child_ids/currency_id/parent_id,
 * ``disallowed_ancestor_companies`` carries the same minus ``currency_id`` —
 * which is why that one key is optional here. ``parent_id`` is the raw id (0 /
 * falsy at the root), not a many2one pair.
 *
 * Only `id` is guaranteed. The rest are optional on purpose: the session
 * payload varies by source (`disallowed_ancestor_companies` carries no
 * `currency_id`), `patchWithCleanup` in tests installs `{id}`-only stubs, and
 * the implementation types its own backing arrays `any[]` for exactly this
 * reason. Requiring them would make correct call sites and fixtures fail.
 *
 * @typedef {Object} UserCompany
 * @property {number} id
 * @property {string} [name]
 * @property {number} [sequence]
 * @property {number[]} [child_ids]
 * @property {number} [parent_id] - falsy for a root company
 * @property {number} [currency_id] - absent on disallowed ancestors
 */

/**
 * @typedef {Object} UserObject
 * @property {string} name - display name
 * @property {string} login - username / email
 * @property {boolean} isAdmin - is ERP manager
 * @property {boolean} isSystem - has system group
 * @property {boolean} isInternalUser - has internal user group
 * @property {number} partnerId - res.partner ID
 * @property {number|false} homeActionId - default home action
 * @property {boolean} showEffect - whether to show UI effects (confetti, etc.)
 * @property {number} userId - res.users ID
 * @property {string} writeDate - partner write date (for avatar cache busting)
 * @property {Record<string, any>} context - user context (lang, tz, uid, allowed_company_ids)
 * @property {string} lang - BCP 47 locale string
 * @property {string} tz - timezone identifier
 * @property {Record<string, any>} settings - res.users.settings snapshot
 * @property {(update: Object) => void} updateContext - merge keys into the user context
 * @property {(group: string) => Promise<boolean>} hasGroup - check group membership (cached)
 * @property {(model: string, operation: string, ids?: number[]|number, options?: {context?: Object}) => Promise<boolean>} checkAccessRight - check model ACL. `ids` accepts a scalar (the implementation runs it through `ensureArray`). Cached by [model, operation, ids] ONLY; passing `options.context` bypasses the cache entirely because the key omits the context and a company-dependent answer would otherwise poison it. Do not drop the 4th argument at a call site to satisfy a type — it is load-bearing (see `user.test.js` "explicit context bypasses the cache").
 * @property {(key: string, value: any) => Promise<void>} setUserSettings - persist a setting to the server
 * @property {(key: string, value: any) => void} updateUserSettings - update a setting locally (no RPC)
 * @property {UserCompany | undefined} defaultCompany - fallback company from session
 * @property {UserCompany[]} allowedCompanies - authorized companies
 * @property {UserCompany[]} allowedCompaniesWithAncestors - includes disallowed ancestors
 * @property {UserCompany[]} activeCompanies - currently selected companies
 * @property {UserCompany} activeCompany - primary active company
 * @property {(companyIds: number[], options?: {includeChildCompanies?: boolean, reload?: boolean}) => Promise<void>} activateCompanies - switch active companies
 */

export const userBus = new EventBus();

/** @returns {number[]} */
function getCookieCompanyIds() {
    const cids = cookie.get("cids");
    if (typeof cids === "string") {
        return cids.split("-").map(Number);
    }
    return [];
}

/**
 * Build the user object from session data. Exposed for testing so each test
 * suite can construct an isolated instance with fresh caches.
 *
 * @param {Record<string, any>} session - the raw session payload from the server
 * @returns {UserObject} the user singleton with identity, companies, and access APIs
 */
export function _makeUser(session) {
    const {
        home_action_id: homeActionId,
        is_admin: isAdmin,
        is_internal_user: isInternalUser,
        is_system: isSystem,
        is_public: isPublic,
        name,
        partner_id: partnerId,
        show_effect: showEffect,
        uid: userId,
        username: login,
        user_context: context,
        user_settings,
        partner_write_date: writeDate,
        user_companies: userCompanies,
        groups = {},
    } = session;
    const settings = user_settings || {};

    /**
     * Update the list of active companies from cookie IDs, falling back to
     * the default company if the cookie values are stale or empty.
     * @param {number[]} cids - company IDs from the cookie
     * @param {Array<{id: number, child_ids: number[]}>} allowedCompanies
     * @param {{id: number} | undefined} defaultCompany
     */
    function updateActiveCompanies(cids, allowedCompanies, defaultCompany) {
        const previousIds = activeCompanies.map((c) => c.id).join("-");
        activeCompanies = cids
            .map((cid) => allowedCompanies.find((c) => c.id === cid))
            .filter((c) => c !== undefined);
        if (!activeCompanies.length) {
            // .map((c) => c.id) never receives undefined elements.
            const fallback = defaultCompany || allowedCompanies[0];
            activeCompanies = fallback ? [fallback] : [];
        }
        if (activeCompanies.length) {
            activeCompanies = [
                activeCompanies[0],
                ...sortBy(activeCompanies.slice(1), (c) => c.id),
            ];
        }

        const activeIds = activeCompanies.map((c) => c.id);
        cookie.set("cids", activeIds.join("-"));
        Object.assign(context, { allowed_company_ids: activeIds });

        // Every listener of this event does expensive invalidation work: the
        // group and access-right caches are dropped and reseeded here, and the
        // whole display-name cache is dropped in `name_service`. Re-selecting
        // the companies already active (re-clicking the same entry in the
        // company switcher, a recovery path that adds an id already present)
        // must not pay for that.
        if (activeIds.join("-") !== previousIds) {
            userBus.trigger(UserEvent.ACTIVE_COMPANIES_CHANGED);
        }
    }

    /** @type {any[]} */
    let allowedCompanies = [];
    /** @type {any[]} */
    const allowedCompaniesWithAncestors = [];
    /** @type {any[]} */
    let activeCompanies = [];
    /** @type {any} */
    let defaultCompany;

    if (userCompanies) {
        allowedCompanies = Object.values(userCompanies.allowed_companies);
        allowedCompaniesWithAncestors.push(
            ...Object.values(userCompanies.allowed_companies),
        );
        if (userCompanies.disallowed_ancestor_companies) {
            allowedCompaniesWithAncestors.push(
                ...Object.values(userCompanies.disallowed_ancestor_companies),
            );
        }
        defaultCompany = allowedCompanies.find(
            (c) => c.id === userCompanies.current_company,
        );
        updateActiveCompanies(getCookieCompanyIds(), allowedCompanies, defaultCompany);
    }

    delete session.home_action_id;
    delete session.is_admin;
    delete session.is_internal_user;
    delete session.is_system;
    delete session.name;
    delete session.partner_id;
    delete session.show_effect;
    delete session.uid;
    delete session.username;
    delete session.user_context;
    delete session.user_settings;
    delete session.partner_write_date;
    delete session.user_companies;
    delete session.groups;

    /** @type {(group: string, context: Object) => Promise<boolean>} */
    const getGroupCacheValue = (group, context) => {
        if (!userId) {
            return Promise.resolve(false);
        }
        return rpc("/web/dataset/call_kw/res.users/has_group", {
            model: "res.users",
            method: "has_group",
            args: [userId, group],
            kwargs: { context },
        });
    };
    const getGroupCacheKey = (/** @type {string} */ group) => group;
    const groupCache = new Cache(getGroupCacheValue, getGroupCacheKey);
    const seedGroupCache = () => {
        /** @type {[string, boolean | undefined][]} */
        const seeded = [
            ["base.group_user", isInternalUser],
            ["base.group_system", isSystem],
            ["base.group_erp_manager", isAdmin],
            ["base.group_public", isPublic],
        ];
        for (const [group, value] of seeded) {
            if (value !== undefined) {
                groupCache.set(Promise.resolve(value), group);
            }
        }
        for (const [group, value] of Object.entries(groups)) {
            groupCache.set(Promise.resolve(!!value), group);
        }
    };
    seedGroupCache();
    /** @type {(model: string, operation: string, ids: number[], context: Object) => Promise<boolean>} */
    const getAccessRightCacheValue = (model, operation, ids, context) => {
        const url = `/web/dataset/call_kw/${model}/has_access`;
        return rpc(url, {
            model,
            method: "has_access",
            args: [ids, operation],
            kwargs: { context },
        });
    };
    const getAccessRightCacheKey = (
        /** @type {string} */ model,
        /** @type {string} */ operation,
        /** @type {number[]} */ ids,
    ) => JSON.stringify([model, operation, ids]);
    const accessRightCache = new Cache(
        getAccessRightCacheValue,
        getAccessRightCacheKey,
    );
    userBus.addEventListener(UserEvent.ACTIVE_COMPANIES_CHANGED, () => {
        groupCache.invalidate();
        seedGroupCache();
        accessRightCache.invalidate();
    });
    const lang = pyToJsLocale(context?.lang);

    return {
        name,
        login,
        isAdmin,
        isSystem,
        isInternalUser,
        partnerId,
        homeActionId,
        showEffect,
        userId,
        writeDate,
        get context() {
            return { ...context, uid: this.userId };
        },
        get lang() {
            return lang;
        },
        get tz() {
            // Read the closure directly: `this.context` builds a fresh spread
            // of the whole context object just to pluck one key.
            return context.tz;
        },
        get settings() {
            return { ...settings };
        },
        updateContext(update) {
            Object.assign(context, update);
        },
        hasGroup(group) {
            return groupCache.read(group, this.context);
        },
        checkAccessRight(
            model,
            operation,
            ids = [],
            { context } = /** @type {{ context?: object }} */ ({}),
        ) {
            if (context) {
                return getAccessRightCacheValue(
                    model,
                    operation,
                    ensureArray(ids),
                    context,
                );
            }
            return accessRightCache.read(
                model,
                operation,
                ensureArray(ids),
                this.context,
            );
        },
        async setUserSettings(key, value) {
            const model = "res.users.settings";
            const method = "set_res_users_settings";
            const changedSettings = await rpc(
                `/web/dataset/call_kw/${model}/${method}`,
                {
                    model,
                    method,
                    // Closure, not `this.settings`: the getter spreads the whole
                    // settings object just to read one key (same reason the `tz`
                    // getter reads `context` directly).
                    args: [[settings.id]],
                    kwargs: {
                        new_settings: {
                            [key]: value,
                        },
                        context: this.context,
                    },
                },
            );
            Object.assign(settings, changedSettings);
        },
        updateUserSettings(key, value) {
            settings[key] = value;
        },
        defaultCompany,
        allowedCompanies,
        allowedCompaniesWithAncestors,
        get activeCompanies() {
            return activeCompanies;
        },
        get activeCompany() {
            return activeCompanies?.[0];
        },
        async activateCompanies(
            companyIds,
            { includeChildCompanies = true, reload = true } = {},
        ) {
            const newCompanyIds = companyIds.length
                ? [...companyIds]
                : activeCompanies[0]
                  ? [activeCompanies[0].id]
                  : [];

            /**
             * `child_ids` is optional on a UserCompany (see the typedef:
             * `disallowed_ancestor_companies` omits keys, and test fixtures
             * install `{id}`-only stubs), so it must never be spread or
             * iterated raw — `for…of undefined` throws.
             * @param {number} companyId
             * @returns {number[]}
             */
            function childIdsOf(companyId) {
                return (
                    allowedCompanies.find((c) => c.id === companyId)?.child_ids ?? []
                );
            }

            function addCompanies(/** @type {number[]} */ companyIds) {
                for (const companyId of companyIds) {
                    if (!newCompanyIds.includes(companyId)) {
                        newCompanyIds.push(companyId);
                        addCompanies(childIdsOf(companyId));
                    }
                }
            }

            if (includeChildCompanies) {
                addCompanies(companyIds.flatMap(childIdsOf));
            }

            updateActiveCompanies(newCompanyIds, allowedCompanies, defaultCompany);

            if (reload) {
                browser.location.reload();
            }
        },
    };
}

export const user = _makeUser(session);

const LAST_CONNECTED_USER_KEY = "web.lastConnectedUser";

/** @returns {any[]} */
export const getLastConnectedUsers = () => {
    const raw = browser.localStorage.getItem(LAST_CONNECTED_USER_KEY);
    if (!raw) {
        return [];
    }
    try {
        const users = JSON.parse(raw);
        // `JSON.parse` happily returns a number, string or object here; every
        // caller then does `.filter` / `.slice` on it and throws, bricking the
        // quick-login list until localStorage is cleared by hand.
        if (!Array.isArray(users)) {
            browser.localStorage.removeItem(LAST_CONNECTED_USER_KEY);
            return [];
        }
        return users;
    } catch {
        browser.localStorage.removeItem(LAST_CONNECTED_USER_KEY);
        return [];
    }
};

/** @param {any[]} users */
export const setLastConnectedUsers = (users) => {
    browser.localStorage.setItem(
        LAST_CONNECTED_USER_KEY,
        JSON.stringify(users.slice(0, 5)),
    );
};

if (!session._quick_login_processed) {
    if (!session.quick_login) {
        if (browser.localStorage.getItem(LAST_CONNECTED_USER_KEY) !== null) {
            browser.localStorage.removeItem(LAST_CONNECTED_USER_KEY);
        }
    } else if (user.login && user.login !== "__system__") {
        const users = getLastConnectedUsers();
        const lastConnectedUsers = [
            {
                login: user.login,
                name: user.name,
                partnerId: user.partnerId,
                partnerWriteDate: user.writeDate,
                userId: user.userId,
            },
            ...users.filter((u) => u.userId !== user.userId),
        ];
        setLastConnectedUsers(lastConnectedUsers);
    }
    session._quick_login_processed = true;
    delete session.quick_login;
}
