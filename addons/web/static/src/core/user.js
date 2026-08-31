// @ts-check
/** @odoo-module native */

import { EventBus } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { cookie } from "@web/core/browser/cookie";
import { readJSONStorage, writeJSONStorage } from "@web/core/browser/storage_json";
import { UserEvent } from "@web/core/events";
import { pyToJsLocale } from "@web/core/l10n/utils";
import { rpc } from "@web/core/network/rpc";
import { ensureArray, sortBy, unique } from "@web/core/utils/collections/arrays";
import { Cache } from "@web/core/utils/collections/cache";
import { session } from "@web/session";

/**
 * @typedef {Object} UserCompany
 * @property {number} id
 * @property {string} [name]
 * @property {number} [sequence]
 * @property {number[]} [child_ids]
 * @property {number} [parent_id]
 * @property {number} [currency_id]
 */

/**
 * @typedef {Object} UserObject
 * @property {string} name
 * @property {string} login
 * @property {boolean} isAdmin
 * @property {boolean} isSystem
 * @property {boolean} isInternalUser
 * @property {number} partnerId
 * @property {number|false} homeActionId
 * @property {boolean} showEffect
 * @property {number} userId
 * @property {string} writeDate
 * @property {Record<string, any>} context
 * @property {string} lang
 * @property {string} tz
 * @property {Record<string, any>} settings
 * @property {(update: Object) => void} updateContext
 * @property {(group: string) => Promise<boolean>} hasGroup
 * @property {(model: string, operation: string, ids?: number[]|number, options?: {context?: Object}) => Promise<boolean>} checkAccessRight
 * @property {(key: string, value: any) => Promise<void>} setUserSettings
 * @property {(key: string, value: any) => void} updateUserSettings
 * @property {UserCompany | undefined} defaultCompany
 * @property {UserCompany[]} allowedCompanies
 * @property {UserCompany[]} allowedCompaniesWithAncestors
 * @property {UserCompany[]} activeCompanies
 * @property {UserCompany} activeCompany
 * @property {(companyIds: number[], options?: {includeChildCompanies?: boolean, reload?: boolean}) => Promise<void>} activateCompanies
 * @property {() => void} _onActiveCompaniesChanged
 */

export const userBus = new EventBus();

/**
 * @type {number}
 */
export const SUPERUSER_ID = 1;

/** @returns {number[]} */
function getCookieCompanyIds() {
    const cids = cookie.get("cids");
    if (typeof cids === "string") {
        return cids.split("-").map(Number);
    }
    return [];
}

const USER_KEYS_OWNED_BY_USER = [
    "home_action_id",
    "is_admin",
    "is_internal_user",
    "is_system",
    "name",
    "partner_id",
    "show_effect",
    "uid",
    "username",
    "user_context",
    "user_settings",
    "partner_write_date",
    "user_companies",
    "groups",
];

/**
 * The user's company set: which are allowed, which are active, and how
 * activating one pulls its children in.
 *
 * Extracted from _makeUser because it is the one part of the user object with
 * rules of its own -- an ordering (the main company first, the rest by id), a
 * fallback when the cookie names nothing valid, a cookie to keep in step, and an
 * event other services listen for. None of that has anything to do with groups,
 * settings or access rights; it only shared a closure with them.
 *
 * @param {any} userCompanies session.user_companies
 * @param {Record<string, any>} context the user context, whose allowed_company_ids this owns
 */
function makeCompanies(userCompanies, context) {
    /** @type {any[]} */
    let allowedCompanies = [];
    /** @type {any[]} */
    const allowedCompaniesWithAncestors = [];
    /** @type {any[]} */
    let activeCompanies = [];
    /** @type {any} */
    let defaultCompany;

    /**
     * @param {number[]} cids
     */
    function setActive(cids) {
        const previousIds = activeCompanies.map((c) => c.id).join("-");
        activeCompanies = cids
            .map((cid) => allowedCompanies.find((c) => c.id === cid))
            .filter((c) => c !== undefined);
        if (!activeCompanies.length) {
            const fallback = defaultCompany || allowedCompanies[0];
            activeCompanies = fallback ? [fallback] : [];
        }
        if (activeCompanies.length) {
            // The main company keeps its place; the rest are ordered by id so
            // that the same selection always produces the same cookie.
            activeCompanies = [
                activeCompanies[0],
                ...sortBy(activeCompanies.slice(1), (c) => c.id),
            ];
        }

        const activeIds = activeCompanies.map((c) => c.id);
        cookie.set("cids", activeIds.join("-"));
        Object.assign(context, { allowed_company_ids: activeIds });

        if (activeIds.join("-") !== previousIds) {
            userBus.trigger(UserEvent.ACTIVE_COMPANIES_CHANGED);
        }
    }

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
        setActive(getCookieCompanyIds());
    }

    /**
     * @param {number} companyId
     * @returns {number[]}
     */
    function childIdsOf(companyId) {
        return allowedCompanies.find((c) => c.id === companyId)?.child_ids ?? [];
    }

    return {
        get allowedCompanies() {
            return allowedCompanies;
        },
        get allowedCompaniesWithAncestors() {
            return allowedCompaniesWithAncestors;
        },
        get activeCompanies() {
            return activeCompanies;
        },
        get defaultCompany() {
            return defaultCompany;
        },
        /**
         * @param {number[]} companyIds
         * @param {{ includeChildCompanies?: boolean }} [options]
         */
        activate(companyIds, { includeChildCompanies = true } = {}) {
            const newCompanyIds = companyIds.length
                ? [...companyIds]
                : activeCompanies[0]
                  ? [activeCompanies[0].id]
                  : [];

            const addCompanies = (/** @type {number[]} */ ids) => {
                for (const companyId of ids) {
                    if (!newCompanyIds.includes(companyId)) {
                        newCompanyIds.push(companyId);
                        addCompanies(childIdsOf(companyId));
                    }
                }
            };
            if (includeChildCompanies) {
                addCompanies(companyIds.flatMap(childIdsOf));
            }
            setActive(newCompanyIds);
        },
    };
}

/**
 * `hasGroup`, memoised, and pre-seeded with what the session already told us.
 *
 * @param {number | false} userId
 * @param {Record<string, any>} groups session.groups
 * @param {{ isInternalUser?: boolean, isSystem?: boolean, isAdmin?: boolean, isPublic?: boolean }} flags
 */
function makeGroupCache(userId, groups, flags) {
    const cache = new Cache(
        (/** @type {string} */ group, /** @type {object} */ context) => {
            if (!userId) {
                return Promise.resolve(false);
            }
            return rpc("/web/dataset/call_kw/res.users/has_group", {
                model: "res.users",
                method: "has_group",
                args: [userId, group],
                kwargs: { context },
            });
        },
        // Keyed on the group alone: the context is an argument to the RPC, not
        // part of the question being cached.
        (/** @type {string} */ group) => group,
    );

    function seed() {
        /** @type {[string, boolean | undefined][]} */
        const seeded = [
            ["base.group_user", flags.isInternalUser],
            ["base.group_system", flags.isSystem],
            ["base.group_erp_manager", flags.isAdmin],
            ["base.group_public", flags.isPublic],
        ];
        for (const [group, value] of seeded) {
            if (value !== undefined) {
                cache.set(Promise.resolve(value), group);
            }
        }
        for (const [group, value] of Object.entries(groups)) {
            cache.set(Promise.resolve(!!value), group);
        }
    }
    seed();

    return {
        /**
         * @param {string} group
         * @param {object} context
         * @returns {Promise<boolean>}
         */
        has(group, context) {
            return cache.read(group, context);
        },
        /** Drop every answer and put the session's own back. */
        reseed() {
            cache.invalidate();
            seed();
        },
    };
}

/**
 * `has_access`, memoised on (model, operation, id SET) -- so the same question
 * asked with the ids in another order, or with duplicates, is one RPC.
 */
function makeAccessRightCache() {
    const fetch = (
        /** @type {string} */ model,
        /** @type {string} */ operation,
        /** @type {number[]} */ ids,
        /** @type {object} */ context,
    ) =>
        rpc(`/web/dataset/call_kw/${model}/has_access`, {
            model,
            method: "has_access",
            args: [ids, operation],
            kwargs: { context },
        });

    const cache = new Cache(fetch, (model, operation, ids) =>
        JSON.stringify([
            model,
            operation,
            unique([...ids]).sort((a, b) => (a > b ? 1 : a < b ? -1 : 0)),
        ]),
    );

    return {
        /**
         * @param {string} model
         * @param {string} operation
         * @param {number[]} ids
         * @param {object} context
         * @param {{ cached?: boolean }} [options]
         * @returns {Promise<boolean>}
         */
        check(model, operation, ids, context, { cached = true } = {}) {
            return cached
                ? cache.read(model, operation, ids, context)
                : fetch(model, operation, ids, context);
        },
        invalidate() {
            cache.invalidate();
        },
    };
}

/**
 * @param {Record<string, any>} session
 * @returns {UserObject}
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

    const companies = makeCompanies(userCompanies, context);

    const groups_ = makeGroupCache(userId, groups, {
        isInternalUser,
        isSystem,
        isAdmin,
        isPublic,
    });
    const accessRights = makeAccessRightCache();
    const lang = pyToJsLocale(context?.lang);

    return {
        _onActiveCompaniesChanged() {
            groups_.reseed();
            accessRights.invalidate();
        },
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
            return context.tz;
        },
        get settings() {
            return { ...settings };
        },
        updateContext(update) {
            Object.assign(context, update);
        },
        hasGroup(group) {
            return groups_.has(group, this.context);
        },
        checkAccessRight(
            model,
            operation,
            ids = [],
            { context } = /** @type {{ context?: object }} */ ({}),
        ) {
            // An explicit context is not part of the cache key, so it must not
            // be answered from the cache either.
            return accessRights.check(
                model,
                operation,
                ensureArray(ids),
                context ?? this.context,
                { cached: !context },
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
        get defaultCompany() {
            return companies.defaultCompany;
        },
        get allowedCompanies() {
            return companies.allowedCompanies;
        },
        get allowedCompaniesWithAncestors() {
            return companies.allowedCompaniesWithAncestors;
        },
        get activeCompanies() {
            return companies.activeCompanies;
        },
        get activeCompany() {
            return companies.activeCompanies?.[0];
        },
        async activateCompanies(companyIds, options = {}) {
            companies.activate(companyIds, options);
            if (options.reload ?? true) {
                browser.location.reload();
            }
        },
    };
}

export const user = _makeUser(session);

for (const key of USER_KEYS_OWNED_BY_USER) {
    delete session[key];
}

userBus.addEventListener(UserEvent.ACTIVE_COMPANIES_CHANGED, () =>
    user._onActiveCompaniesChanged(),
);

const LAST_CONNECTED_USER_KEY = "web.lastConnectedUser";

/** @returns {any[]} */
export const getLastConnectedUsers = () =>
    readJSONStorage(LAST_CONNECTED_USER_KEY, {
        fallback: /** @type {any[]} */ ([]),
        validate: Array.isArray,
        clearOnInvalid: true,
    });

/** @param {any[]} users */
export const setLastConnectedUsers = (users) => {
    writeJSONStorage(LAST_CONNECTED_USER_KEY, users.slice(0, 5));
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
