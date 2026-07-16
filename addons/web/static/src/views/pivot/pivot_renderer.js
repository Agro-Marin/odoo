// @ts-check
/** @odoo-module native */

/** @module @web/views/pivot/pivot_renderer - Renders the pivot table HTML with expandable row/column headers, measures dropdown, and XLSX export */

import { Component, onWillRender, useRef } from "@odoo/owl";
import { CheckBox } from "@web/components/checkbox/checkbox";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { DropdownState } from "@web/components/dropdown/dropdown_hooks";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { getFieldCodec } from "@web/core/field_codec";
import { localization } from "@web/core/l10n/localization";
import { _t } from "@web/core/l10n/translation";
import { download } from "@web/core/network/download";
import { sortBy } from "@web/core/utils/collections/arrays";
import { useService } from "@web/core/utils/hooks";
import { useRenderCounter } from "@web/core/utils/render_instrumentation";
import { useReactiveModel } from "@web/model/model";
import { CustomGroupByItem } from "@web/search/custom_group_by_item/custom_group_by_item";
import { PropertiesGroupByItem } from "@web/search/properties_group_by_item/properties_group_by_item";
import { getIntervalOptions } from "@web/search/utils/dates";
import { GROUPABLE_TYPES } from "@web/search/utils/misc";
import { user } from "@web/services/user";
import { usePopover } from "@web/ui/popover/popover_hook";
import { MultiCurrencyPopover } from "@web/views/view_components/multi_currency_popover";
import { ReportViewMeasures } from "@web/views/view_components/report_view_measures";

class PivotDropdown extends Dropdown {
    /**
     * @override
     */
    get position() {
        return this.props.state.position || "bottom-start";
    }
    /**
     * @override
     */
    get target() {
        return this.props.state.target;
    }
}

export class PivotRenderer extends Component {
    static template = "web.PivotRenderer";
    static components = {
        CheckBox,
        CustomGroupByItem,
        Dropdown,
        DropdownItem,
        PivotDropdown,
        PropertiesGroupByItem,
        ReportViewMeasures,
    };
    static props = ["model", "buttonTemplate"];

    setup() {
        useRenderCounter("pivot.PivotRenderer");
        this.actionService = useService("action");
        this.notification = useService("notification");
        // Subscribe directly to model.notify(): the model prop is stable,
        // so this renderer only updated through the legacy deep-render
        // listener before (PivotModel now opts out of it via
        // ``reactiveRenderers``). The epoch guard keeps unrelated local
        // re-renders (dropdown state, hover) from recomputing the table.
        this.model = useReactiveModel(this.props.model);
        // Per-render cache of the <td> lists highlighted on column hover:
        // the DOM may change on any render, but between two renders (where
        // the bulk of mouseover/mouseout traffic happens) the cells of a
        // column are stable, so each column is queried at most once.
        this.columnCellsCache = new Map();
        this.hoveredCells = null;
        // Per-render cache of the group-by menu items: the ``groupByItems``
        // getter is read several times per render (t-foreach, its t-if guard,
        // and onGroupBySelected's lookup) and rebuilds the list each time.
        // Cleared every render below, so it only dedupes intra-render reads and
        // can't go stale across renders.
        this.groupByItemsCache = null;
        let tableEpoch;
        onWillRender(() => {
            this.columnCellsCache.clear();
            this.hoveredCells = null;
            this.groupByItemsCache = null;
            if (this.model._updateEpoch !== tableEpoch) {
                tableEpoch = this.model._updateEpoch;
                this.table = this.model.getTable();
                this.computeMeasureFormatters();
            }
        });
        this.l10n = localization;
        this.tableRef = useRef("table");

        this.dropdown = {
            state: new DropdownState({
                onClose: () => {
                    delete this.dropdown.cellInfo;
                    delete this.dropdown.state.target;
                    delete this.dropdown.state.position;
                },
            }),
        };
        this.multiCurrencyPopover = usePopover(MultiCurrencyPopover, {
            position: "right",
        });
        const fields = [];
        for (const [fieldName, field] of Object.entries(
            this.env.searchModel.searchViewFields,
        )) {
            if (this.validateField(fieldName, field)) {
                fields.push(Object.assign({ name: fieldName }, field));
            }
        }
        this.fields = sortBy(fields, "string");
    }
    /**
     * Precompute the codec and base format options for each active measure.
     *
     * `getFormattedValue` runs once per body cell per render; rebuilding the
     * fieldInfo + codec + options there would repeat the same derivation for
     * every cell (cf. the memoization in view_utils.getFormattedValue). Only
     * per-cell bits (e.g. currencyId) are resolved per cell.
     *
     * @private
     */
    computeMeasureFormatters() {
        const { fieldAttrs, measures, widgets, activeMeasures } = this.model.metaData;
        /** @type {Map<string, { codec: any, formatType: string, baseOptions: Record<string, any> }>} */
        this.measureFormatters = new Map();
        for (const measure of activeMeasures) {
            const field = measures[measure];
            const attrs = fieldAttrs[measure] ?? {};
            const fieldInfo = {
                options: attrs.options ?? {},
                attrs,
            };
            let formatType = widgets[measure];
            if (!formatType) {
                const fieldType = field.type;
                formatType = ["many2one", "reference"].includes(fieldType)
                    ? "integer"
                    : fieldType;
            }
            const codec = getFieldCodec(formatType);
            this.measureFormatters.set(measure, {
                codec,
                formatType,
                baseOptions: { field, ...codec.extractOptions(fieldInfo) },
            });
        }
    }
    /**
     * Left/right padding (px) applied to a row header cell to indent it by its
     * depth in the row-group tree.
     *
     * Kept as an overridable method (rather than inlined in the template) so
     * downstream addons can adjust the per-level indent — web_enterprise's
     * mobile pivot patches this to shrink the step so deep trees stay on
     * screen. Inlining orphaned that patch; template calls this instead.
     *
     * @param {Object} cell - row header cell with an ``indent`` depth
     * @returns {number}
     */
    getPadding(cell) {
        return 5 + cell.indent * 30;
    }
    /**
     * @private
     * @param {Object} cell
     * @returns {string}
     */
    getFormattedValue(cell) {
        const { codec, formatType, baseOptions } = this.measureFormatters.get(
            cell.measure,
        );
        // Shallow-copy per cell: some formatters self-mutate their options
        /** @type {Record<string, any>} */
        const formatOptions = { ...baseOptions };
        // currencyIds is only populated for true monetary fields that declare a
        // currency_field (see pivot_measurements.js getCurrencyIds). A plain
        // measure forced to the "monetary" format via widget="monetary" has no
        // currencyIds, so guard the dereference to avoid crashing every cell.
        if (formatType === "monetary" && cell.currencyIds) {
            if (cell.currencyIds.length > 1) {
                formatOptions.currencyId = user.activeCompany?.currency_id;
                return /** @type {any} */ ({
                    rawValue: cell.value,
                    value: codec.format(cell.value, formatOptions),
                    currencies: cell.currencyIds,
                    help: this.getFullPrecisionHelp(cell, codec, formatOptions),
                });
            }
            formatOptions.currencyId = cell.currencyIds[0];
        }
        return /** @type {any} */ ({
            value: codec.format(cell.value, formatOptions),
            help: this.getFullPrecisionHelp(cell, codec, formatOptions),
        });
    }
    /**
     * Full-precision tooltip for humanized cells: when the formatter
     * shortens the value (options.human_readable), expose the plain
     * formatted value as the cell's data-tooltip.
     *
     * @private
     * @param {Object} cell
     * @param {any} codec
     * @param {Record<string, any>} formatOptions
     * @returns {string|undefined}
     */
    getFullPrecisionHelp(cell, codec, formatOptions) {
        if (!formatOptions.humanReadable) {
            return undefined;
        }
        return codec.format(cell.value, { ...formatOptions, humanReadable: false });
    }

    /**
     * @returns {Object[]}
     */
    get groupByItems() {
        if (this.groupByItemsCache) {
            return this.groupByItemsCache;
        }
        let items = this.env.searchModel.getSearchItems(
            (searchItem) =>
                ["groupBy", "dateGroupBy"].includes(searchItem.type) &&
                !searchItem.custom,
        );
        if (!items.length) {
            // Copy: ``this.fields`` is the renderer's own array (built once in
            // setup and passed to <CustomGroupByItem/>). The custom-groupby loop
            // below pushes onto ``items``, and this getter is re-evaluated several
            // times per menu render — aliasing would append the custom groupbys to
            // ``this.fields`` on every call, growing it unboundedly.
            items = [...this.fields];
        }

        // Add custom groupbys
        let groupNumber = 1 + Math.max(0, ...items.map(({ groupNumber: n }) => n || 0));
        for (const [
            fieldName,
            customGroupBy,
        ] of this.model.metaData.customGroupBys.entries()) {
            items.push({
                ...customGroupBy,
                name: fieldName,
                groupNumber: groupNumber++,
            });
        }

        this.groupByItemsCache = items.map((item) => ({
            ...item,
            id: item.id || item.name,
            fieldName: item.fieldName || item.name,
            description: item.description || item.string,
            options:
                item.options ||
                (["date", "datetime"].includes(item.type)
                    ? getIntervalOptions()
                    : undefined),
        }));
        return this.groupByItemsCache;
    }

    /**
     * @returns {boolean}
     */
    get hideCustomGroupBy() {
        return this.env.searchModel.hideCustomGroupBy || false;
    }

    /**
     * @param {string} fieldName
     * @param {Object} field
     * @returns {boolean}
     */
    validateField(fieldName, field) {
        const { groupable, type } = field;
        return groupable && fieldName !== "id" && GROUPABLE_TYPES.includes(type);
    }

    // Handlers

    /**
     * Handle the adding of a custom groupby (inside the view, not the searchview).
     *
     * @param {string} fieldName
     */
    onAddCustomGroupBy(fieldName) {
        this.model.addGroupBy({
            ...this.dropdown.cellInfo,
            fieldName,
            custom: true,
        });
        this.dropdown.state.close();
    }

    /**
     * @param {Object} param0
     * @param {number} param0.itemId
     * @param {number} [param0.optionId]
     */
    onGroupBySelected({ itemId, optionId }) {
        const { fieldName } = this.groupByItems.find(({ id }) => id === itemId);
        this.model.addGroupBy({
            ...this.dropdown.cellInfo,
            fieldName,
            interval: optionId,
        });
    }
    /**
     * @param {PointerEvent} ev
     * @param {Object} cell
     * @param {boolean} isXAxis
     */
    onHeaderClick(ev, cell, isXAxis) {
        const type = isXAxis ? "col" : "row";
        if (cell.isLeaf && !cell.isFolded) {
            if (this.dropdown.state.isOpen) {
                this.dropdown.state.close();
            } else {
                this.dropdown.cellInfo = { type, groupId: cell.groupId };
                Object.assign(this.dropdown.state, {
                    target: /** @type {HTMLElement} */ (ev.target).closest(
                        ".o_pivot_header_cell_closed",
                    ),
                    position: isXAxis ? "bottom-start" : "bottom-end",
                    isOpen: true,
                });
            }
        } else if (cell.isLeaf && cell.isFolded) {
            this.model.expandGroup(cell.groupId, type);
        } else if (!cell.isLeaf) {
            this.model.closeGroup(cell.groupId, type);
        }
    }
    /**
     * @param {Object} cell
     */
    onMeasureClick(cell) {
        this.model.sortRows({
            groupId: cell.groupId,
            measure: cell.measure,
            order: (cell.order || "desc") === "asc" ? "desc" : "asc",
        });
    }
    /**
     * Hover the column in which the mouse is.
     *
     * @param {MouseEvent} ev
     */
    onMouseEnter(ev) {
        const current = /** @type {HTMLElement} */ (ev.currentTarget);
        let index = [...current.parentNode.children].indexOf(current);
        if (current.tagName === "TH") {
            index += 1; // row groupbys column
        }
        let cells = this.columnCellsCache.get(index);
        if (!cells) {
            cells = this.tableRef.el.querySelectorAll(`td:nth-child(${index + 1})`);
            this.columnCellsCache.set(index, cells);
        }
        cells.forEach((elt) => elt.classList.add("o_cell_hover"));
        this.hoveredCells = cells;
    }
    onMouseLeave() {
        // Fall back to a full sweep when a render invalidated the cache
        // while a column was highlighted.
        const cells =
            this.hoveredCells ?? this.tableRef.el.querySelectorAll(".o_cell_hover");
        cells.forEach((elt) => elt.classList.remove("o_cell_hover"));
        this.hoveredCells = null;
    }

    /**
     * Exports the current pivot table data in a xls file. For this, we have to
     * serialize the current state, then call the server /web/pivot/export_xlsx.
     */
    onDownloadButtonClicked() {
        if (this.model.getTableWidth() > 16384) {
            // Surface a user-facing notification rather than throwing from a
            // click handler, which would trip the generic crash dialog and
            // abort the handler abnormally.
            this.notification.add(
                _t(
                    "For Excel compatibility, data cannot be exported if there are more than 16384 columns.\n\nTip: try to flip axis, filter further or reduce the number of measures.",
                ),
                { type: "danger", sticky: true },
            );
            return;
        }
        const table = this.model.exportData();
        download({
            url: "/web/pivot/export_xlsx",
            data: {
                data: new Blob([JSON.stringify(table)], {
                    type: "application/json",
                }),
            },
        });
    }
    onExpandButtonClicked() {
        this.model.expandAll();
    }
    onFlipButtonClicked() {
        this.model.flip();
    }
    /**
     * Toggles the given measure
     *
     * @param {Object} param0
     * @param {string} param0.measure
     */
    onMeasureSelected({ measure }) {
        this.model.toggleMeasure(measure);
    }
    openMultiCurrencyPopover(ev, value, currencyIds) {
        if (!this.multiCurrencyPopover.isOpen) {
            this.multiCurrencyPopover.open(ev.target, {
                currencyIds,
                target: ev.target,
                value,
            });
        }
    }
    /**
     * Execute the action to open the view on the current model.
     *
     * @param {Array} domain
     * @param {Array} views
     * @param {Object} context
     */
    openView(domain, views, context, newWindow) {
        this.actionService.doAction(
            {
                type: "ir.actions.act_window",
                name: this.model.metaData.title,
                res_model: this.model.metaData.resModel,
                search_view_id: this.env.config.views?.find((v) => v[1] === "search"),
                views: views,
                view_mode: "list",
                target: "current",
                context,
                domain,
            },
            {
                newWindow,
            },
        );
    }
    /**
     * @param {Object} cell
     * @param {boolean} [newWindow]
     */
    onOpenView(cell, newWindow) {
        if (cell.value === undefined || this.model.metaData.disableLinking) {
            return;
        }

        const context = { ...this.model.searchParams.context };
        for (const x of Object.keys(context)) {
            if (x === "group_by" || x.startsWith("search_default_")) {
                delete context[x];
            }
        }

        // retrieve form and list view ids from the action
        const { views = [] } = this.env.config;
        this.views = ["list", "form"].map((viewType) => {
            const view = views.find((view) => view[1] === viewType);
            return [view ? view[0] : false, viewType];
        });

        const group = {
            rowValues: cell.groupId[0],
            colValues: cell.groupId[1],
        };
        this.openView(this.model.getGroupDomain(group), this.views, context, newWindow);
    }
}
