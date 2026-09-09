// @ts-check

import { ensureArray } from "@web/core/utils/collections/arrays";
import { session } from "@web/session";
import {
    parseHomeMenuConfig,
    readHomeMenuConfig,
} from "@web/webclient/menus/menu_utils";

import { ServerModel } from "../mock_model.js";

const ORM_AUTOMATIC_FIELDS = new Set([
    "create_date",
    "create_uid",
    "display_name",
    "name",
    "write_date",
    "write_uid",
]);

export class ResUsersSettings extends ServerModel {
    _name = "res.users.settings";

    /** @param {number|number[]} userIdOrIds */
    _get_or_create_for_user(userIdOrIds) {
        const [userId] = ensureArray(userIdOrIds);
        const settings = /** @type {any} */ (this)._filter([
            ["user_id", "=", userId],
        ])[0];
        if (settings) {
            return settings;
        }
        const settingsId = this.create(/** @type {any} */ ({ user_id: userId }));
        return this.browse(settingsId)[0];
    }

    /**
     * @param {number} id
     * @param {string[]} [fields_to_format]
     */
    res_users_settings_format(id, fields_to_format) {
        const [settings] = this.browse(id);
        /** @type {(entry: [string, unknown]) => boolean} */
        const filterPredicate = fields_to_format
            ? ([fieldName]) => fields_to_format.includes(fieldName)
            : ([fieldName]) => !ORM_AUTOMATIC_FIELDS.has(fieldName);
        const res = Object.fromEntries(
            Object.entries(settings).filter(/** @type {any} */ (filterPredicate)),
        );
        if (Reflect.ownKeys(res).includes("user_id")) {
            res.user_id = { id: settings.user_id };
        }
        return res;
    }

    /** @param {number | number[]} ids */
    update_homemenu_config(ids, changes) {
        const [id] = ensureArray(ids);
        const [settings] = this.browse(id);
        let config = readHomeMenuConfig(settings.homemenu_config);
        for (const { operation, xmlid, value } of changes) {
            if (operation === "reset") {
                config = null;
                continue;
            }
            config ??= parseHomeMenuConfig(session.homemenu_default_config);
            if (operation === "order" || operation === "pinned_order") {
                const key = operation === "order" ? "order" : "pinned";
                const requested = [...new Set(/** @type {string[]} */ (value))].filter(
                    (item) => key === "order" || config?.pinned.includes(item),
                );
                config[key] = [
                    ...requested,
                    ...config[key].filter((item) => !requested.includes(item)),
                ];
            } else if (xmlid) {
                const key = operation === "pin" ? "pinned" : "hidden";
                if (!value) {
                    config[key] = config[key].filter((item) => item !== xmlid);
                }
                if (value) {
                    if (!config[key].includes(xmlid)) {
                        config[key].push(xmlid);
                    }
                    const other = key === "pinned" ? "hidden" : "pinned";
                    config[other] = config[other].filter((item) => item !== xmlid);
                }
            }
        }
        const homemenu_config = config && { version: 2, ...config };
        this.write(id, { homemenu_config });
        return { id, homemenu_config };
    }

    /**
     * @param {number | Iterable<number>} idOrIds
     * @param {Record<string, unknown>} new_settings
     */
    set_res_users_settings(idOrIds, new_settings) {
        const [id] = ensureArray(idOrIds);
        const [oldSettings] = this.browse(id);
        if (!oldSettings) {
            throw new Error(
                `res.users.settings: no record with id ${JSON.stringify(id)}. ` +
                    `Seed one for the session, e.g. ` +
                    `patchWithCleanup(user, _makeUser({ user_settings: { id: 1 } })) ` +
                    `together with a matching record on the model.`,
            );
        }
        /** @type {Record<string, unknown>} */
        const changedSettings = {};
        for (const setting in new_settings) {
            if (
                setting in oldSettings &&
                new_settings[setting] !== oldSettings[setting]
            ) {
                changedSettings[setting] = new_settings[setting];
            }
        }
        this.write(id, changedSettings);
        return changedSettings;
    }
}
