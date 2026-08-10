/** @odoo-module native */
import {patch} from "@web/core/utils/patch";
import {virtualOperatorFunctions} from "@web/core/tree";
import {
    introduceDateRangeOperators,
    eliminateDateRangeOperators,
} from "./date_range_virtual_operators.js";

/**
 * Patch the virtual operators module to include date range operators.
 *
 * Introduction runs last so the web client's own operators get first claim on
 * the patterns they own; elimination runs first, mirroring that order, so a
 * daterange is back to plain `<=`/`>=` conditions before the standard passes
 * look at the tree.
 *
 * `operate()` normalizes every connector it rebuilds, so no extra flattening
 * pass is needed after elimination.
 */
patch(virtualOperatorFunctions, {
    /**
     * Introduce virtual operators including date range operators.
     *
     * @param {Object} tree - Condition tree to process
     * @param {Object} [options={}] - Processing options
     * @param {Function} [options.getFieldDef] - Function to get field definitions
     * @returns {Object} Tree with all virtual operators introduced
     */
    introduceVirtualOperators(tree, options = {}) {
        return introduceDateRangeOperators(
            super.introduceVirtualOperators(tree, options),
            options
        );
    },

    /**
     * Eliminate virtual operators including date range operators.
     *
     * @param {Object} tree - Condition tree to process
     * @param {Object} [options={}] - Processing options
     * @returns {Object} Tree with all virtual operators eliminated
     */
    eliminateVirtualOperators(tree, options = {}) {
        return super.eliminateVirtualOperators(
            eliminateDateRangeOperators(tree, options),
            options
        );
    },
});
