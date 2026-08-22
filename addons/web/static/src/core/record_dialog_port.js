// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";

/** @typedef {import("registries").DialogsRegistryItemShape} DialogConstructor */

/**
 * @returns {DialogConstructor}
 */
export function getSelectCreateDialog() {
    return registry.category("dialogs").get("select_create");
}

/**
 * @returns {DialogConstructor}
 */
export function getFormViewDialog() {
    return registry.category("dialogs").get("form_view");
}
