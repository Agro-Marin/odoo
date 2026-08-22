// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";

/**
 * @type {import("@web/core/registry").Registry<import("registries").SharedComponentsRegistryItemShape>}
 */
export const sharedComponents = registry.category("shared_components");

sharedComponents.addValidation((entry) => typeof entry === "function");
