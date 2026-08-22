// @ts-check
/** @odoo-module native */

import { getAction } from "@web/core/action_port";

/**
 * @param {import("@web/env").OdooEnv} env
 * @param {string} title
 * @param {string} model
 * @param {number} id
 * @returns {Promise<void>}
 */
export async function editModelDebug(env, title, model, id) {
    await getAction(env).doAction({
        res_model: model,
        res_id: id,
        name: title,
        type: "ir.actions.act_window",
        views: [[false, "form"]],
        view_mode: "form",
        target: "current",
    });
}
