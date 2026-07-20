// @ts-check
/** @odoo-module native */

/** @module @web/views/kanban/kanban_controller - Controller for the kanban view with grouping, quick-create, and progress bar support */

import { reactive, useEffect, useState } from "@odoo/owl";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { useSetupAction } from "@web/core/action_hook";
import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { useModelWithSampleData } from "@web/model/model";
import {
    addFieldDependencies,
    extractFieldsFromArchInfo,
} from "@web/model/relational_model/utils";
import { ActionMenus } from "@web/search/action_menus/action_menus";
import { Layout } from "@web/search/layout";
import { usePager } from "@web/search/pager_hook";
import { SearchBar } from "@web/search/search_bar/search_bar";
import { MultiRecordController } from "@web/views/multi_record_controller";
import { standardViewProps } from "@web/views/standard_view_props";
import { MultiRecordViewButton } from "@web/views/view_button/multi_record_view_button";
import { SelectionBox } from "@web/views/view_components/selection_box";
import { buildMultiRecordModelParams } from "@web/views/view_utils";

import { KanbanCogMenu } from "./kanban_cog_menu.js";
import { KanbanRenderer } from "./kanban_renderer.js";
import { useProgressBar } from "./progress_bar_hook.js";

const QUICK_CREATE_FIELD_TYPES = [
    "char",
    "boolean",
    "many2one",
    "selection",
    "many2many",
];

/**
 * Main controller for the kanban view, extending MultiRecordController.
 *
 * Manages the kanban-specific model (with sample data support), progress bar
 * state, quick-create workflow, column scroll restoration, and record CRUD
 * actions (open, create, delete). Coordinates between the KanbanRenderer,
 * RelationalModel, and pager.
 */
export class KanbanController extends MultiRecordController {
    static template = `web.KanbanView`;
    static components = {
        ActionMenus,
        DropdownItem,
        Layout,
        KanbanRenderer,
        MultiRecordViewButton,
        SearchBar,
        CogMenu: KanbanCogMenu,
        SelectionBox,
    };
    static props = {
        ...standardViewProps,
        editable: { type: Boolean, optional: true },
        forceGlobalClick: { type: Boolean, optional: true },
        onSelectionChanged: { type: Function, optional: true },
        readonly: { type: Boolean, optional: true },
        showButtons: { type: Boolean, optional: true },
        Compiler: Function,
        Model: Function,
        Renderer: Function,
        buttonTemplate: String,
        archInfo: Object,
    };

    static defaultProps = {
        createRecord: () => {},
        forceGlobalClick: false,
        selectRecord: () => {},
        showButtons: true,
    };

    setup() {
        super.setup();

        // --- Kanban-specific model with sample data override ---
        const { Model } = this.props;

        class KanbanSampleModel extends Model {
            hasData() {
                if (this.root.groups && !this.root.groups.length) {
                    // No groups yet: show the column quick-create and example
                    // background instead of sample data.
                    return true;
                }
                return super.hasData();
            }

            removeSampleDataInGroups() {
                if (this.useSampleModel) {
                    for (const group of this.root.groups) {
                        const list = group.list;
                        group.count = 0;
                        list.count = 0;
                        if (list._records !== undefined) {
                            list._records = [];
                        } else {
                            list.groups = [];
                        }
                    }
                }
            }
        }

        this.model = useState(
            useModelWithSampleData(
                /** @type {any} */ (KanbanSampleModel),
                this.modelParams,
                /** @type {any} */ (this.modelOptions),
            ),
        );

        // --- Progress bar ---
        if (this.archInfo.progressAttributes) {
            const { activeBars } = this.props.state || {};
            this.progressBarState = useProgressBar(
                this.archInfo.progressAttributes,
                this.model,
                this.progressBarAggregateFields,
                activeBars,
            );
        }
        this.headerButtons = this.archInfo.headerButtons;

        // --- Quick create ---
        //
        // Side-effecting setter (Pattern 4, STATE_MANAGEMENT.md): opening a
        // quick-create while sample data is visible must clear the samples
        // synchronously with the ``groupId`` mutation, or sample records
        // still paint while the form mounts. A useEffect-based migration
        // (commit 19fb5d01bb81) was reverted because the deferred timing
        // broke 3 sample-data integration tests in kanban_view.test.js.
        const self = this;
        this.quickCreateState = reactive(
            /** @type {any} */ ({
                get groupId() {
                    return this._groupId || false;
                },
                // eslint-disable-next-line no-restricted-syntax -- synchronous timing contract; see comment above
                set groupId(groupId) {
                    if (self.model.useSampleModel) {
                        self.model.removeSampleDataInGroups();
                        self.model.useSampleModel = false;
                    }
                    this._groupId = groupId;
                },
                view: this.archInfo.quickCreateView,
            }),
        );

        // --- Common post-model behavior ---
        this.initMultiRecordBehavior();

        // --- Kanban-specific hooks ---
        const { setScrollFromState } = useSetupAction({
            rootRef: this.rootRef,
            beforeUnload: this.beforeUnload.bind(this),
            beforeLeave: this.beforeLeave.bind(this),
            getLocalState: () => {
                const state = {
                    activeBars: this.progressBarState?.activeBars,
                    modelState: this.model.exportState(),
                };
                if (this.env.isSmall && this.model.root.isGrouped) {
                    const columnScrollTops = [];
                    const sel = ".o_kanban_group:not(.o_column_folded)";
                    const columnEls = /** @type {HTMLElement} */ (
                        this.rootRef.el
                    ).querySelectorAll(sel);
                    const groups = this.model.root.groups;
                    for (const columnEl of columnEls) {
                        const scrollTop = columnEl.scrollTop;
                        if (scrollTop > 0) {
                            const group = groups.find(
                                (g) => g.id === columnEl.dataset.id,
                            );
                            // The DOM can hold a column the model no longer
                            // knows (mid-patch snapshot while leaving the
                            // action); skip it rather than break navigation.
                            if (group) {
                                columnScrollTops.push([
                                    group.serverValue,
                                    columnEl.scrollTop,
                                ]);
                            }
                        }
                    }
                    state.scrollPositions = {
                        scrollLeft:
                            this.rootRef.el?.querySelector(".o_renderer")?.scrollLeft ||
                            0,
                        columnScrollTops,
                    };
                }
                return state;
            },
        });
        useEffect(
            (isReady) => {
                if (isReady) {
                    if (this.env.isSmall && this.model.root.isGrouped) {
                        const { scrollPositions } = this.props.state || {};
                        if (scrollPositions) {
                            const { scrollLeft, columnScrollTops } = scrollPositions;
                            const renderer =
                                this.rootRef.el?.querySelector(".o_renderer");
                            if (renderer) {
                                renderer.scrollLeft = scrollLeft;
                            }
                            const groups = this.model.root.groups;
                            for (const [serverValue, scrollTop] of columnScrollTops) {
                                const group = groups.find(
                                    (g) => g.serverValue === serverValue,
                                );
                                if (group) {
                                    const sel = `.o_kanban_group[data-id="${group.id}"]`;
                                    const el = this.rootRef.el?.querySelector(sel);
                                    if (el) {
                                        el.scrollTop = scrollTop;
                                    }
                                }
                            }
                        }
                    } else {
                        setScrollFromState();
                    }
                }
            },
            () => [this.model.isReady],
        );
        usePager(() => {
            const root = this.model.root;
            const { count, hasLimitedCount, isGrouped, limit, offset } = root;
            if (!isGrouped && !this.model.useSampleModel) {
                return {
                    offset: offset,
                    limit: limit,
                    total: count,
                    onUpdate: async ({ offset, limit }, hasNavigated) => {
                        await this.model.root.load({ offset, limit });
                        await this.onUpdatedPager();
                        if (hasNavigated) {
                            this.onPageChangeScroll();
                        }
                    },
                    updateTotal: hasLimitedCount ? () => root.fetchCount() : undefined,
                };
            }
        });
    }

    // Getters

    /**
     * Configuration object passed to the RelationalModel constructor.
     *
     * Delegates the shared multi-record skeleton (state restoration,
     * countLimit, defaultOrderBy, activeIdsLimit, hooks merge) to
     * ``buildMultiRecordModelParams``; this getter only owns the
     * kanban-specific bits (cardColorField + progressBar field
     * dependencies, ``maxGroupByDepth: 1``, no group limit).
     *
     * @returns {Object}
     */
    get modelParams() {
        const { resModel, limit } = this.props;
        const { activeFields, fields } = extractFieldsFromArchInfo(
            this.archInfo,
            this.props.fields,
        );

        const cardColorField = this.archInfo.cardColorField;
        if (cardColorField) {
            addFieldDependencies(activeFields, fields, [
                { name: cardColorField, type: "integer" },
            ]);
        }

        addFieldDependencies(activeFields, fields, this.progressBarAggregateFields);

        return buildMultiRecordModelParams({
            archInfo: this.archInfo,
            props: this.props,
            uiHooks: this._uiHooks,
            config: {
                resModel,
                activeFields,
                fields,
                fieldsToAggregate: this.progressBarAggregateFields.map(
                    (field) => field.name,
                ),
                openGroupsByDefault: true,
            },
            hooks: {
                lifecycle: {
                    onRecordSaved: this.onRecordSaved.bind(this),
                },
            },
            extras: {
                limit: this.archInfo.limit || limit || 40,
                groupsLimit: Number.MAX_SAFE_INTEGER, // no limit
                maxGroupByDepth: 1,
            },
        });
    }

    /** @returns {Object[]} Fields to aggregate in progress bar computations. */
    get progressBarAggregateFields() {
        const res = [];
        const { progressAttributes } = this.props.archInfo;
        if (progressAttributes?.sumField) {
            res.push(progressAttributes.sumField);
        }
        return res;
    }

    get className() {
        if (this.env.isSmall && this.model.root.isGrouped) {
            const classList = (this.props.className || "").split(" ");
            classList.push("o_action_delegate_scroll");
            return classList.join(" ");
        }
        return this.props.className;
    }

    /** @returns {boolean} Whether the user can create new records. */
    get canCreate() {
        return this.props.archInfo.activeActions.create;
    }

    /** @returns {boolean} Whether the "New" button should be disabled (e.g. empty many2one grouping). */
    get isNewButtonDisabled() {
        const { createGroup } = this.props.archInfo.activeActions;
        const list = this.model.root;
        return (
            this.model.isReady &&
            list.isGrouped &&
            list.groupByField.type === "many2one" &&
            !list.groups.length &&
            createGroup
        );
    }

    /** @returns {boolean} Whether quick-create is available for the current group-by field. */
    get canQuickCreate() {
        const { activeActions } = this.props.archInfo;
        if (!activeActions.quickCreate) {
            return false;
        }
        if (!this.model.isReady) {
            return false;
        }

        const list = this.model.root;
        if (list.groups && !list.groups.length) {
            return false;
        }

        return this.isQuickCreateField(list.groupByField);
    }

    // Methods

    /** @returns {Object[]} Field definitions eligible for data export (excludes properties). */
    getExportableFields() {
        return Object.keys(this.model.root.config.activeFields)
            .map((e) => this.model.root.fields[e])
            .filter(Boolean)
            .filter((field) => field.exportable !== false)
            .filter((field) => field.type !== "properties");
    }

    async beforeUnload() {}

    async beforeLeave() {
        // wait for potential pending write operations (e.g. records being moved)
        return this.model.mutex.getUnlockedDef();
    }

    /**
     * Evaluate a view modifier expression in the current context.
     * @param {string} modifier - Boolean expression string.
     * @returns {boolean}
     */
    evalViewModifier(modifier) {
        return evaluateBooleanExpr(modifier, { context: this.props.context });
    }

    /**
     * Delete a single record with a confirmation dialog.
     * @param {Object} record - The record datapoint to delete.
     */
    deleteRecord(record) {
        this.deleteRecordsWithConfirmation(this.deleteConfirmationDialogProps, [
            record,
        ]);
    }

    async openRecord(record, /** @type {any} */ { newWindow } = {}) {
        const activeIds = this.model.root.records.map((datapoint) => datapoint.resId);
        this.props.selectRecord(record.resId, { activeIds, newWindow });
    }

    /**
     * Create a new record via quick-create, custom action, or default flow.
     * Dispatches based on the `on_create` arch attribute.
     */
    async createRecord() {
        const { onCreate } = this.props.archInfo;
        const { root } = this.model;
        if (this.canQuickCreate && onCreate === "quick_create") {
            const firstGroup =
                root.groups.find((group) => !group.isFolded) || root.groups[0];
            if (firstGroup.isFolded) {
                await firstGroup.toggle();
            }
            this.quickCreateState.groupId = firstGroup.id;
        } else if (onCreate && onCreate !== "quick_create") {
            const options = {
                additionalContext: root.context,
                onClose: async (/** @type {any} */ { noReload } = {}) => {
                    if (!noReload) {
                        await root.load();
                        this.model.useSampleModel = false;
                        this.render(true); // Force re-render: model.useSampleModel change is not reactive
                    }
                },
            };
            await this.actionService.doAction(onCreate, options);
        } else {
            await this.props.createRecord();
        }
    }

    /**
     * Update progress bar counts after a record is saved in a grouped view.
     * @param {Object} record - The saved record datapoint.
     */
    onRecordSaved(record) {
        if (this.model.root.isGrouped) {
            const group = this.model.root.groups.find((l) =>
                l.records.find((r) => r.id === record.id),
            );
            this.progressBarState?.updateCounts(group, record);
        }
    }

    async onUpdatedPager() {}

    /** Scroll the content area to the top. */
    scrollTop() {
        this.rootRef.el?.querySelector(".o_content")?.scrollTo({ top: 0 });
    }

    /**
     * Check whether a field type supports quick-create grouping.
     * @param {Object | null} field - Field definition with a `type` property.
     * @returns {boolean}
     */
    isQuickCreateField(field) {
        return field && QUICK_CREATE_FIELD_TYPES.includes(field.type);
    }
}
