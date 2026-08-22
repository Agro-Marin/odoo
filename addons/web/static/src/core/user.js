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

    /**
     * @param {number[]} cids
     * @param {Array<{id: number, child_ids: number[]}>} allowedCompanies
     * @param {{id: number} | undefined} defaultCompany
     */
    function updateActiveCompanies(cids, allowedCompanies, defaultCompany) {
        const previousIds = activeCompanies.map((c) => c.id).join("-");
        activeCompanies = cids
            .map((cid) => allowedCompanies.find((c) => c.id === cid))
            .filter((c) => c !== undefined);
        if (!activeCompanies.length) {
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
    /**
     * @type {(model: string, operation: string, ids: number[], context: Object) => Promise<boolean>}
     */
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
    ) =>
        JSON.stringify([
            model,
            operation,
            unique([...ids]).sort((a, b) => (a > b ? 1 : a < b ? -1 : 0)),
        ]);
    const accessRightCache = new Cache(
        getAccessRightCacheValue,
        getAccessRightCacheKey,
    );
    const lang = pyToJsLocale(context?.lang);

    return {
        _onActiveCompaniesChanged() {
            groupCache.invalidate();
            seedGroupCache();
            accessRightCache.invalidate();
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
