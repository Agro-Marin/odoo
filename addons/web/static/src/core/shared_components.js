// @ts-check
/** @odoo-module native */

/** @module @web/core/shared_components */

import { registry } from "@web/core/registry";

/**
 * Late-binding seam between `@web/views` and `@web/fields`, which cannot import
 * each other directly.
 *
 * @type {import("@web/core/registry").Registry<import("registries").SharedComponentsRegistryItemShape>}
 */
export const sharedComponents = registry.category("shared_components");

sharedComponents.addValidation((entry) => typeof entry === "function");
