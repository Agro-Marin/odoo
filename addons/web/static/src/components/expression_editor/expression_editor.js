// @ts-check
/** @odoo-module native */

import { Component, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { makeDefaultCondition } from "@web/components/domain_selector/utils";
import { getExpressionDisplayedOperators } from "@web/components/expression_editor/expression_editor_operator_editor";
import { ModelFieldSelector } from "@web/components/model_field_selector/model_field_selector";
import { getOperatorEditorInfo, TreeEditor } from "@web/components/tree_editor";
import { _t } from "@web/core/translation";
import { expressionFromTree } from "@web/core/tree/expression_from_tree";
import { treeFromExpression } from "@web/core/tree/tree_from_expression";
export class ExpressionEditor extends Component {
    static template = "web.ExpressionEditor";
    static components = { TreeEditor };
    static props = {
        resModel: String,
        fields: Object,
        expression: String,
        update: Function,
    };

    /**
     * @type {Record<string, Record<string, any>>}
     */
    filteredFields = {};

    setup() {
        onWillStart(() => this.onPropsUpdated(this.props));
        onWillUpdateProps((nextProps) => this.onPropsUpdated(nextProps));
    }

    /**
     * @param {typeof this.props} props
     * @returns {Promise<void>}
     */
    async onPropsUpdated(props) {
        this.filteredFields = Object.fromEntries(
            Object.entries(props.fields).filter(
                ([_, fieldDef]) => fieldDef.type !== "properties",
            ),
        );
        try {
            this.tree = treeFromExpression(/** @type {string} */ (props.expression), {
                getFieldDef: (name) =>
                    this.getFieldDef(/** @type {string | number} */ (name), props),
                distributeNot: !this.isDebugMode,
                generateSmartDates: false,
            });
        } catch {
            this.tree = null;
        }
    }

    /**
     * @param {string | number} name
     * @param {typeof this.props} [props]
     * @returns {Object | null}
     */
    getFieldDef(name, props = this.props) {
        if (typeof name === "string") {
            return props.fields[name] || null;
        }
        return null;
    }

    /**
     * @returns {Object}
     */
    getDefaultCondition() {
        return makeDefaultCondition(
            this.filteredFields,
            getExpressionDisplayedOperators,
        );
    }

    /**
     * @param {Object} fieldDef
     * @returns {string}
     */
    getDefaultOperator(fieldDef) {
        return getExpressionDisplayedOperators(fieldDef)[0];
    }

    /**
     * @param {Object} fieldDef
     * @returns {any}
     */
    getOperatorEditorInfo(fieldDef) {
        const operators = getExpressionDisplayedOperators(fieldDef);
        return getOperatorEditorInfo(operators, fieldDef);
    }

    /**
     * @param {string} resModel
     * @param {Object} defaultCondition
     * @returns {Object}
     */
    getPathEditorInfo(resModel, defaultCondition) {
        if (resModel !== this.props.resModel) {
            throw new Error(
                `Expression editor doesn't support tree as value so resModel has to be props.resModel`,
            );
        }
        return {
            component: ModelFieldSelector,
            extractProps: ({ value, update }) => ({
                path: value,
                update,
                resModel: this.props.resModel,
                readonly: false,
                filter: (fieldDef) => fieldDef.name in this.filteredFields,
                showDebugInput: false,
                followRelations: false,
                isDebugMode: this.isDebugMode,
            }),
            isSupported: (value) =>
                [0, 1].includes(value) || value in this.filteredFields,
            stringify: (value) => this.props.fields[value].string,
            defaultValue: () => defaultCondition.path,
            message: _t("Field properties not supported"),
        };
    }

    get isDebugMode() {
        return !!this.env.debug;
    }

    /**
     * @param {string} expression
     */
    onExpressionChange(expression) {
        this.props.update(expression);
    }

    resetExpression() {
        this.props.update("True");
    }

    /**
     * @param {Object} tree
     */
    update(tree) {
        let expression;
        try {
            expression = expressionFromTree(/** @type {any} */ (tree), {
                getFieldDef: (name) =>
                    this.getFieldDef(/** @type {string | number} */ (name)),
                generateSmartDates: false,
            });
        } catch {
            expression = this.props.expression;
        }
        this.props.update(expression);
    }
}
