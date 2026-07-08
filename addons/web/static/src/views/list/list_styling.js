// @ts-check
/** @odoo-module native */

/** @module @web/views/list/list_styling - Class-name + formatted-value helpers extracted from ListRenderer */

/**
 * Styling cohort extracted from ``ListRenderer``.
 *
 * The methods below were originally instance methods on
 * ``ListRenderer.prototype``.  They are exported as a plain mixin
 * object that ``list_renderer.js`` applies to its prototype via
 * ``Object.assign(ListRenderer.prototype, listStylingMixin)``.
 *
 * Why prototype assignment instead of a hook (the pattern of
 * ``useListAggregates``, ``useListSelection``, etc.):
 *
 * The ~40 subclasses of ``ListRenderer`` (across ``stock``, ``hr``,
 * ``account``, ``sale``, ``web_studio``, etc. — verified fork-wide
 * count 2026-05-23; an earlier revision of this comment said "~71",
 * which was wrong even at the time it was written) override these
 * methods via ``super.getCellClass(col, record)``,
 * ``super.getRowClass(record)``, ``super.canUseFormatter(...)``.
 * A hook returning a namespaced object (``this.styling.getCellClass``)
 * would force every subclass to be rewritten — out of scope for a
 * refactor that should preserve behavior.  Mixin assignment keeps the
 * methods on the prototype chain so ``super.<method>(...)`` keeps
 * working untouched.
 *
 * The methods read from ``this`` (the renderer instance), not from
 * closed-over state — ``this.cellClassByColumn``, ``this._readonlyCache``,
 * ``this.props``, ``this.fields``, ``this.editedRecord`` all stay on
 * the renderer.  Field initializations (``this.cellClassByColumn = {}``)
 * remain in the renderer's setup; only the method bodies move here.
 */

import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { getClassNameFromDecoration } from "@web/core/utils/decorations";
import { getFormattedValue } from "@web/views/view_utils";

/**
 * Field-type → CSS-class table consulted when building a cell's class
 * string.  Drives ``o_list_number``, ``o_list_text``, etc. — controls
 * column alignment and width hints in CSS.
 */
export const FIELD_CLASSES = {
    char: "o_list_char",
    float: "o_list_number",
    integer: "o_list_number",
    monetary: "o_list_number",
    text: "o_list_text",
    many2one: "o_list_many2one",
};

/**
 * Mixin applied to ``ListRenderer.prototype`` after class declaration.
 * Methods here use ``this`` to access the renderer's reactive state and
 * dependent helpers (``isSortable``, ``isNumericColumn``,
 * ``canResequenceRows``, ``isInlineEditable``, ``editedRecord``,
 * ``columns``, ``fields``).  Those stay on the renderer (some belong to
 * the sorting cohort, extracted separately; others are renderer-local).
 */
export const listStylingMixin = {
    /**
     * Class string applied to a column header ``<th>``.
     *
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
        if (column.type === "button_group") {
            classNames.push("o_list_button");
        }
        if (column.widget) {
            classNames.push(`o_${column.widget}_cell`);
        }
        return classNames.join(" ");
    },

    /**
     * Class string applied to a row ``<tr>`` representing the given
     * record.  Combines arch-defined decorations with selection / edit
     * / drag-handle state classes.
     *
     * @param {import("@web/model/relational_model/record").RelationalRecord} record
     * @returns {string}
     */
    getRowClass(record) {
        /** @type {string[]} Decoration classnames evaluated against the record */
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
        // "o_selected_row" classname for the potential row in edition
        if (record.isInEdition) {
            classNames.push("o_selected_row");
        }
        if (this.canResequenceRows) {
            classNames.push("o_row_draggable");
        }
        return classNames.join(" ");
    },

    /**
     * Class string applied to a cell ``<td>``.
     *
     * Two layers of caching:
     *   - ``this.cellClassByColumn[column.id]`` — column-level base
     *     class (type, widget, button-group); recomputed once per
     *     column.
     *   - ``this._readonlyCache`` — per-render cache for the full
     *     (column × record) class string; cleared on each render
     *     by ``onWillRender``.
     *
     * @param {Object} column
     * @param {import("@web/model/relational_model/record").RelationalRecord} record
     */
    getCellClass(column, record) {
        if (column.relatedPropertyField && !(column.name in record.data)) {
            return "";
        }

        // Per-render cache for the full cell class string (column + record dependent)
        const cacheKey = `cell:${column.id},${record.id}`;
        const cached = this._readonlyCache?.get(cacheKey);
        if (cached !== undefined) {
            return cached;
        }

        if (!this.cellClassByColumn[column.id]) {
            const classNames = ["o_data_cell"];
            if (column.type === "button_group") {
                classNames.push("o_list_button");
            } else if (column.type === "field") {
                classNames.push("o_field_cell");
                if (column.attrs && column.attrs.class && !column.widget) {
                    // When a widget is used, arch classes are delegated only to
                    // the <Field> component (via getFieldClass) so that layout
                    // classes like d-flex do not conflict with the cell layout.
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
            this.cellClassByColumn[column.id] = classNames.join(" ");
        }
        let result = this.cellClassByColumn[column.id];
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
        this._readonlyCache?.set(cacheKey, result);
        return result;
    },

    /**
     * @param {Object} column
     * @param {import("@web/model/relational_model/record").RelationalRecord} record
     * @returns {boolean}
     */
    isCellReadonly(column, record) {
        const cacheKey = `${column.id},${record.id}`;
        let result = this._readonlyCache?.get(cacheKey);
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
        this._readonlyCache?.set(cacheKey, result);
        return result;
    },

    /**
     * Cell ``title`` attribute — the full text shown in a tooltip when
     * a fixed-width column truncates the displayed value.  Limited to
     * scalar string-like fields where the formatted value matches the
     * displayed text.
     *
     * @param {Object} column
     * @param {import("@web/model/relational_model/record").RelationalRecord} record
     * @param {string} [formattedValue] value already formatted for display in
     *  the cell body — passed by the template to avoid formatting twice
     */
    getCellTitle(column, record, formattedValue) {
        if (["many2one", "reference", "char"].includes(this.fields[column.name].type)) {
            return formattedValue !== undefined
                ? formattedValue
                : this.getFormattedValue(column, record);
        }
    },

    /**
     * Class string forwarded to the inner ``<Field>`` component.  Only
     * arch-supplied ``class`` attribute survives — base layout classes
     * (``o_field_cell``) live on the ``<td>``.
     *
     * @param {Object} column
     */
    getFieldClass(column) {
        return column.attrs && column.attrs.class;
    },

    /**
     * Format a record's value for the given column.  Honours the
     * ``enable_formatting=false`` arch option to bypass formatting for
     * raw display, and otherwise delegates to the canonical
     * ``getFormattedValue`` helper from ``view_utils``.
     *
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
     * Evaluate the ``invisible`` arch attribute against a record's
     * eval context (with virtual ids for not-yet-saved x2many rows).
     *
     * @param {string} invisible
     * @param {import("@web/model/relational_model/record").RelationalRecord} record
     */
    evalInvisible(invisible, record) {
        return evaluateBooleanExpr(invisible, record.evalContextWithVirtualIds);
    },

    /**
     * Evaluate the ``column_invisible`` arch attribute against the
     * list-level eval context (no per-record state).
     *
     * @param {string} columnInvisible
     */
    evalColumnInvisible(columnInvisible) {
        return evaluateBooleanExpr(columnInvisible, this.props.list.evalContext);
    },

    /**
     * Whether the formatter (vs the field widget) should render the
     * cell's value.  False for cells that have an explicit widget, and
     * for inline-editable rows currently in edition (so the editable
     * widget renders instead of formatted text).
     *
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
            // In an x2many non-editable list a record may be "in edition" because
            // it's opened in a dialog, but in the list we still want readonly
            // formatting.
            return false;
        }
        return true;
    },

    /**
     * Whether the record itself should render as readonly regardless
     * of column-level overrides.  Captures: new records always
     * editable; ``activeActions.edit === false`` forces readonly;
     * dialog-opened x2many edits stay readonly in the list.
     *
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
