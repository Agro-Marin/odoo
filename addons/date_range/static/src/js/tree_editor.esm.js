/** @odoo-module native */
import {
    deserializeDate,
    deserializeDateTime,
    serializeDate,
    serializeDateTime,
} from "@web/core/l10n/dates";

import {Select} from "@web/components/tree_editor";
import {TreeEditor} from "@web/components/tree_editor";
import {patch} from "@web/core/utils/patch";

/**
 * Return the date range type id encoded in a daterange operator, if any.
 *
 * @param {*} operator - a tree node operator
 * @returns {number|null} the date.range.type id, or null for the generic operator
 */
function dateRangeTypeId(operator) {
    if (typeof operator !== "string" || !operator.startsWith("daterange_")) {
        return null;
    }
    const typeId = Number(operator.slice("daterange_".length));
    return Number.isInteger(typeId) && typeId > 0 ? typeId : null;
}

/**
 * Whether an operator is one of the virtual date range operators.
 *
 * @param {*} operator - a tree node operator
 * @returns {boolean}
 */
function isDateRangeOperator(operator) {
    return typeof operator === "string" && operator.includes("daterange");
}

/**
 * Serialize a date for comparison against a date/datetime field.
 *
 * A date range is inclusive of both its endpoints, so on a datetime field the
 * start becomes the first instant of its day and the end the last instant of
 * its. Getting these the wrong way round (start at 23:59:59, end at 00:00:00)
 * silently narrows the filter by almost two days.
 *
 * @param {string} date - Date string in YYYY-MM-DD format
 * @param {string} type - Field type ('date' or 'datetime')
 * @param {boolean} endOfDay - true for the last instant of the day
 * @returns {string} Serialized date or datetime string
 */
function toDateTime(date, type, endOfDay) {
    if (type === "date") {
        return date;
    }
    const day = deserializeDate(date);
    return serializeDateTime(endOfDay ? day.endOf("day") : day.startOf("day"));
}

/**
 * Convert a datetime string back to the plain date it falls on.
 *
 * @param {string} date - Date or datetime string
 * @param {string} type - Field type ('date' or 'datetime')
 * @returns {string} Serialized date string (YYYY-MM-DD)
 */
function fromDateTime(date, type) {
    if (type === "date") {
        return date;
    }
    return serializeDate(deserializeDateTime(date));
}

/**
 * The pair of values a daterange condition holds, in the order the
 * elimination step consumes them: value[0] feeds `<=`, value[1] feeds `>=`.
 *
 * @param {Object} range - a date.range record
 * @param {string} fieldType - 'date' or 'datetime'
 * @returns {string[]} [upperBound, lowerBound]
 */
function rangeToValue(range, fieldType) {
    return [
        toDateTime(range.date_end, fieldType, true),
        toDateTime(range.date_start, fieldType, false),
    ];
}

/**
 * Ranges selectable for a node, narrowed to the operator's type when it has one.
 *
 * @param {Object} env - component environment
 * @param {*} operator - the node's operator
 * @returns {Object[]} date.range records
 */
function rangesForOperator(env, operator) {
    const all = env.domain?.dateRanges || [];
    const typeId = dateRangeTypeId(operator);
    if (!typeId) {
        return all;
    }
    const filtered = all.filter(
        (range) => range.type_id && range.type_id[0] === typeId
    );
    return filtered.length ? filtered : all;
}

/**
 * Patch TreeEditor to support date range value selection
 */
patch(TreeEditor.prototype, {
    /**
     * Get value editor configuration for a tree node.
     * For daterange operators, this changes the editor to a Select component
     * that shows available date ranges instead of date inputs.
     *
     * @param {Object} node - Tree node being edited
     * @param {string} node.path - Field path
     * @param {string} node.operator - Operator (e.g., "daterange", "daterange_1")
     * @param {Array} node.value - Current value [end, start]
     * @returns {Object} Value editor configuration
     */
    getValueEditorInfo(node) {
        const fieldDef = this.getFieldDef(node.path);
        const info = super.getValueEditorInfo(node);

        const isDateField =
            fieldDef && (fieldDef.type === "date" || fieldDef.type === "datetime");
        if (!isDateField || !isDateRangeOperator(node.operator)) {
            return info;
        }

        // Narrow by this node's own operator. Reading it from an instance
        // attribute set by the last updateLeafOperator call made every
        // daterange row in the tree show the last-edited row's type.
        const dateRanges = rangesForOperator(this.env, node.operator);
        if (!dateRanges.length) {
            return info;
        }

        // Use Select component instead of date inputs
        info.component = Select;

        info.extractProps = ({value, update}) => {
            const selected = dateRanges.find(
                (range) =>
                    range.date_start === fromDateTime(value?.[1], fieldDef.type) &&
                    range.date_end === fromDateTime(value?.[0], fieldDef.type)
            );
            return {
                options: dateRanges.map((dr) => [dr.id, dr.name]),
                update: (rangeId) => {
                    const range = dateRanges.find((r) => r.id === rangeId);
                    if (range) {
                        update(rangeToValue(range, fieldDef.type));
                    }
                },
                value: selected ? selected.id : null,
            };
        };

        info.isSupported = (value) => Array.isArray(value) && value.length === 2;

        return info;
    },

    /**
     * Get operator editor configuration for a tree node.
     * For daterange operators, validates that only daterange operators can be selected.
     *
     * @param {Object} node - Tree node being edited
     * @param {string} node.operator - Current operator
     * @returns {Object} Operator editor configuration
     */
    getOperatorEditorInfo(node) {
        const info = super.getOperatorEditorInfo(node);

        // Wrap isSupported to restrict operator changes
        const originalIsSupported = info.isSupported;
        info.isSupported = (value) => {
            const [operator] = value;
            // If current operator is daterange, only allow other daterange operators
            if (isDateRangeOperator(node.operator)) {
                return isDateRangeOperator(operator);
            }
            return originalIsSupported.call(info, value);
        };

        return info;
    },

    /**
     * Handle operator change on a leaf node.
     * When changing to a daterange operator, initialize the value with the first
     * available date range.
     *
     * @param {Object} node - Tree node being edited
     * @param {string} operator - New operator value
     * @param {boolean} negate - Whether the condition is negated
     */
    updateLeafOperator(node, operator, negate) {
        // The value has to be seeded inside the same updateNode() transaction
        // core opens, otherwise it lands after the tree has already been
        // compared against its previous state and notified.
        return this.updateNode(node, () => {
            this._updateLeafOperator(node, operator, negate);
            const fieldDef = this.getFieldDef(node.path);
            const isDateField =
                fieldDef && (fieldDef.type === "date" || fieldDef.type === "datetime");
            if (!isDateField || !isDateRangeOperator(operator)) {
                return;
            }
            const dateRanges = rangesForOperator(this.env, operator);
            if (dateRanges.length) {
                node.value = rangeToValue(dateRanges[0], fieldDef.type);
            }
        });
    },
});
