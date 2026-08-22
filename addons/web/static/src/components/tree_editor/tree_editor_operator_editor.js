// @ts-check
/** @odoo-module native */

import { Select } from "@web/components/tree_editor/tree_editor_components";
import { _t } from "@web/core/translation";
import {
    getOperatorInfo,
    getOperatorLabel,
    OPERATOR_DESCRIPTIONS,
    toOperator,
} from "@web/core/tree/operator_labels";

export { getOperatorLabel };

/**
 * @typedef {Object} OperatorEditorInfo
 * @property {typeof Select} component
 * @property {(params: {update: Function, value: [import("@web/core/tree/condition_tree").Value, boolean]}) => Object} extractProps
 * @property {() => string} defaultValue
 * @property {(operatorValue: [import("@web/core/tree/condition_tree").Value, boolean]) => boolean} isSupported
 * @property {string} message
 * @property {(operatorValue: [import("@web/core/tree/condition_tree").Value, boolean]) => string} stringify
 */

/**
 * @param {string[]} operators
 * @param {Object} [fieldDef]
 * @returns {OperatorEditorInfo}
 */
export function getOperatorEditorInfo(operators, fieldDef) {
    const defaultOperator = operators[0];
    const operatorsInfo = operators.map((operator) =>
        getOperatorInfo(operator, fieldDef?.type),
    );
    return {
        component: Select,
        extractProps: ({ update, value: [operator, negate] }) => {
            const [operatorKey, operatorLabel] = getOperatorInfo(
                operator,
                fieldDef?.type,
                negate,
            );
            const options = [...operatorsInfo];
            if (!options.some(([key]) => key === operatorKey)) {
                options.push([operatorKey, operatorLabel]);
            }
            return {
                value: operatorKey,
                update: (operatorKey) => update(...toOperator(operatorKey)),
                options,
            };
        },
        defaultValue: () => defaultOperator,
        isSupported: ([operator]) =>
            typeof operator === "string" && operator in OPERATOR_DESCRIPTIONS,
        message: _t("Operator not supported"),
        stringify: ([operator, negate]) =>
            getOperatorLabel(operator, fieldDef?.type, negate),
    };
}
