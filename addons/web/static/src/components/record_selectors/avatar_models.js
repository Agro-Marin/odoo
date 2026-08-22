// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";

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
