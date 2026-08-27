// @ts-check
/** @odoo-module native */

import { OWL_SETUP_HOOKS } from "@web/core/utils/dnd/draggable_hook_builder_owl";
import { useSortable as nativeUseSortable } from "@web/core/utils/dnd/sortable";

/**
 * @type {typeof nativeUseSortable}
 */
export function useSortable(params) {
    return nativeUseSortable(
        /** @type {any} */ ({ ...params, setupHooks: OWL_SETUP_HOOKS }),
    );
}
