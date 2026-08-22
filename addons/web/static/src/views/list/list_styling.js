// @ts-check
/** @odoo-module native */

import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { getClassNameFromDecoration } from "@web/core/utils/decorations";
import { getFormattedValue } from "@web/views/view_utils";

const FIELD_CLASSES = {
    char: "o_list_char",
    float: "o_list_number",
    integer: "o_list_number",
    monetary: "o_list_number",
    text: "o_list_text",
    many2one: "o_list_many2one",
};

export const listStylingMixin = {
    /**
     * @param {{ name: string, widget?: string, hasLabel?: boolean, type?: string }} column
     * @returns {string}
     */
    getColumnClass(column) {
        const classNames = ["align-middle"];
        if (this.isSortable(column)) {
            classNames.push("o_column_sortable", "position-relative", "cursor-pointer");
        } else {
            classNames.push("cursor-default");
        }
        const orderBy = this.props.list.orderBy;
        if (
            orderBy.length &&
            column.widget !== "handle" &&
            orderBy[0].name === column.name &&
            column.hasLabel
        ) {
            classNames.push("table-active");
        }
        if (this.isNumericColumn(column)) {
            classNames.push("o_list_number_th");
        }
        if (column.widget) {
            classNames.push(`o_${column.widget}_cell`);
        }
        return classNames.join(" ");
    },

    /**
     * @param {import("@web/model/relational_model/record").RelationalRecord} record
     * @returns {string}
     */
    getRowClass(record) {
        /** @type {string[]} */
        const classNames = this.props.archInfo.decorations
            .filter((decoration) =>
                evaluateBooleanExpr(
                    decoration.condition,
                    record.evalContextWithVirtualIds,
                ),
            )
            .map((decoration) => decoration.class);
        if (record.selected) {
            classNames.push("table-info", "o_data_row_selected");
        }
        if (record.isInEdition) {
            classNames.push("o_selected_row");
        }
        if (this.canResequenceRows) {
            classNames.push("o_row_draggable");
        }
        return classNames.join(" ");
    },

    /**
     * @param {Object} column
     * @param {import("@web/model/relational_model/record").RelationalRecord} record
     */
    getCellClass(column, record) {
        if (column.relatedPropertyField && !(column.name in record.data)) {
            return "";
        }

        const cacheKey = `cell:${column.id}`;
        let recordCache = this._readonlyCache?.get(String(record.id));
        const cached = recordCache?.get(cacheKey);
        if (cached !== undefined) {
            return cached;
        }

        const memoize = !column.relatedPropertyField;
        let baseClass = memoize ? this.cellClassByColumn[column.id] : undefined;
        if (!baseClass) {
            const classNames = ["o_data_cell"];
            if (column.type === "button_group") {
                classNames.push("o_list_button");
            } else if (column.type === "field") {
                classNames.push("o_field_cell");
                if (column.attrs && column.attrs.class && !column.widget) {
                    classNames.push(column.attrs.class);
                }
                const typeClass = FIELD_CLASSES[this.fields[column.name].type];
                if (typeClass) {
                    classNames.push(typeClass);
                }
                if (column.widget) {
                    classNames.push(`o_${column.widget}_cell`);
                }
            }
            baseClass = classNames.join(" ");
            if (memoize) {
                this.cellClassByColumn[column.id] = baseClass;
            }
        }
        let result = baseClass;
        if (column.type === "field") {
            const evalCtx = record.evalContextWithVirtualIds;
            if (evaluateBooleanExpr(/** @type {any} */ (column.required), evalCtx)) {
                result += " o_required_modifier";
            }
            if (record.isFieldInvalid(column.name)) {
                result += " o_invalid_cell";
            }
            if (this.isCellReadonly(column, record)) {
                result += " o_readonly_modifier";
            }
            if (this.canUseFormatter(column, record)) {
                const decorations = /** @type {Record<string, string>} */ (
                    column.decorations
                );
                for (const decoName of Object.keys(decorations)) {
                    if (evaluateBooleanExpr(decorations[decoName], evalCtx)) {
                        result += ` ${getClassNameFromDecoration(decoName)}`;
                    }
                }
            }
            if (
                record.isInEdition &&
                this.editedRecord &&
                this.isCellReadonly(column, this.editedRecord)
            ) {
                result += " text-muted";
            } else {
                result += " cursor-pointer";
            }
        }
        if (this._readonlyCache) {
            const key = String(record.id);
            recordCache = this._readonlyCache.get(key);
            if (!recordCache) {
                recordCache = new Map();
                this._readonlyCache.set(key, recordCache);
            }
            recordCache.set(cacheKey, result);
        }
        return result;
    },

    /**
     * @param {Object} column
     * @param {import("@web/model/relational_model/record").RelationalRecord} record
     * @returns {boolean}
     */
    isCellReadonly(column, record) {
        const cacheKey = String(column.id);
        let recordCache = this._readonlyCache?.get(String(record.id));
        let result = recordCache?.get(cacheKey);
        if (result !== undefined) {
            return result;
        }
        result = !!(
            this.isRecordReadonly(record) ||
            (column.relatedPropertyField &&
                record.selected &&
                record.model.multiEdit) ||
            evaluateBooleanExpr(
                /** @type {string} */ (column.readonly),
                record.evalContextWithVirtualIds,
            )
        );
        if (this._readonlyCache) {
            if (!recordCache) {
                recordCache = new Map();
                this._readonlyCache.set(String(record.id), recordCache);
            }
            recordCache.set(cacheKey, result);
        }
        return result;
    },

    /**
     * @param {Object} column
     * @param {import("@web/model/relational_model/record").RelationalRecord} record
     * @param {string} [formattedValue]
     */
    getCellTitle(column, record, formattedValue) {
        if (["many2one", "reference", "char"].includes(this.fields[column.name].type)) {
            return formattedValue !== undefined
                ? formattedValue
                : this.getFormattedValue(column, record);
        }
    },

    /**
     * @param {Object} column
     */
    getFieldClass(column) {
        return column.attrs && column.attrs.class;
    },

    /**
     * @param {Object} column
     * @param {import("@web/model/relational_model/record").RelationalRecord} record
     */
    getFormattedValue(column, record) {
        const fieldName = column.name;
        if (/** @type {any} */ (column.options)?.enable_formatting === false) {
            const value = record.data[fieldName];
            return value === false ? "" : value;
        }
        return getFormattedValue(record, fieldName, column);
    },

    /**
     * @param {string} invisible
     * @param {import("@web/model/relational_model/record").RelationalRecord} record
     */
    evalInvisible(invisible, record) {
        return evaluateBooleanExpr(invisible, record.evalContextWithVirtualIds);
    },

    /**
     * @param {string} columnInvisible
     */
    evalColumnInvisible(columnInvisible) {
        return evaluateBooleanExpr(columnInvisible, this.props.list.evalContext);
    },

    /**
     * @param {Object} column
     * @param {import("@web/model/relational_model/record").RelationalRecord} record
     */
    canUseFormatter(column, record) {
        if (column.widget) {
            return false;
        }
        if (
            record.isInEdition &&
            (record.model.multiEdit || this.isInlineEditable(record))
        ) {
            return false;
        }
        return true;
    },

    /**
     * @param {import("@web/model/relational_model/record").RelationalRecord} record
     */
    isRecordReadonly(record) {
        if (record.isNew) {
            return false;
        }
        if (this.props.activeActions?.edit === false) {
            return true;
        }
        if (
            record.isInEdition &&
            !this.isInlineEditable(record) &&
            !record.model.multiEdit
        ) {
            return true;
        }
        return false;
    },
};
