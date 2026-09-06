// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";
import { isId } from "@web/core/tree/utils";
import { imageUrl } from "@web/core/utils/urls";

/**
 * @type {import("@web/core/registry").Registry<boolean>}
 */
export const avatarModels = registry.category("avatar_models");

avatarModels.add("res.partner", true).add("res.users", true);

/**
 * @param {string} resModel
 * @returns {boolean}
 */
export function isAvatarModel(resModel) {
    return avatarModels.contains(resModel);
}

/**
 * @param {string} resModel
 * @param {number} resId
 * @returns {string}
 */
export function avatarUrl(resModel, resId) {
    return imageUrl(resModel, resId, "avatar_128");
}

/**
 * The avatar a tag shows for a value, or `false` when the model has none or
 * the value is not a record id.
 *
 * @param {string} resModel
 * @param {any} id
 * @returns {string | false}
 */
export function tagAvatar(resModel, id) {
    return isAvatarModel(resModel) && isId(id) && avatarUrl(resModel, id);
}
