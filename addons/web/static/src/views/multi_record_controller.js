// @ts-check
/** @odoo-module native */

import { onMounted, onWillStart, useEffect, useSubEnv } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { user } from "@web/core/user";
import { KeepLast, SupersededError } from "@web/core/utils/concurrency";
import { usePager } from "@web/search/pager_hook";
import { useViewButtons } from "@web/views/view_button/view_button_hook";
import { useViewChassis } from "@web/views/view_components/view_layout";
import { ViewController } from "@web/views/view_controller";
import { useDeleteRecords, useExportRecords } from "@web/views/view_hook";
import {
    computeArchiveEnabled,
    computeModelOptions,
    prepareStaticActionMenuItems,
} from "@web/views/view_utils";

const log = makeLogger("web.view.multi_record");

export class MultiRecordController extends ViewController {
    /**
     * @param {string} modifier
     * @returns {boolean}
     */
    evalViewModifier(modifier) {
        return evaluateBooleanExpr(modifier, this.model.root.evalContext);
    }

    /** @returns {any[]} */
    get headerButtons() {
        return this.archInfo.headerButtons;
    }

    /** @returns {any[]} the header buttons shown whether or not records are selected */
    get alwaysHeaderButtons() {
        return this.headerButtons.filter(
            (button) =>
                button.display === "always" && !this.evalViewModifier(button.invisible),
        );
    }

    /** @returns {any[]} the header buttons shown on the current selection */
    get selectionHeaderButtons() {
        return this.headerButtons.filter(
            (button) =>
                button.display !== "always" &&
                !this.evalViewModifier(button.invisible) &&
                this.displaySelectionButton(button),
        );
    }

    /**
     * Whether a selection header button applies to the current selection; a
     * controller narrows it to the records a button can act on.
     *
     * @param {any} button
     * @returns {boolean}
     */
    displaySelectionButton(button) {
        return true;
    }

    /** @type {any} */
    model;

    /** @type {boolean} */
    archiveEnabled;
    /** @type {any} */
    searchBarToggler;
    /** @type {boolean} */
    firstLoad;
    /** @type {any} */
    exportRecords;
    /** @type {any} */
    deleteRecordsWithConfirmation;
    /** @type {boolean} */
    isExportEnable = false;
    /** @type {KeepLast<any[]>} */
    _selectionLoads = new KeepLast({ rejectSuperseded: true });
    /** @type {boolean} */
    _multiRecordBehaviorReady = false;

    setup() {
        this.setupControllerServices();
        this.setupModel();
        this.setupArch();
        this.initMultiRecordBehavior();
        this.setupInteractions();
    }

    setupControllerServices() {
        super.setupControllerServices();

        this.archiveEnabled = computeArchiveEnabled(this.props.fields);
        this.chassis = useViewChassis({
            display: () => this.display,
            // list and kanban renderers own their no-content helper
            displayNoContent: () => false,
        });
        this.searchBarToggler = this.chassis.searchBarToggler;
        this.rootRef = this.chassis.rootRef;
        this.firstLoad = true;
        onMounted(() => {
            this.firstLoad = false;
        });
    }

    setupModel() {
        throw new Error(
            `${this.constructor.name} must implement setupModel() to build this.model`,
        );
    }

    initMultiRecordBehavior() {
        if (this._multiRecordBehaviorReady) {
            throw new Error(
                `${this.constructor.name} called initMultiRecordBehavior() twice; ` +
                    "MultiRecordController.setup() already runs it between setupModel() " +
                    "and setupInteractions(). Move the model build into setupModel().",
            );
        }
        this._multiRecordBehaviorReady = true;
        useSubEnv({ model: this.model });

        onWillStart(async () => {
            this.isExportEnable = await user.hasGroup("base.group_allow_export");
        });

        useViewButtons(this.rootRef, {
            beforeExecuteAction: this.beforeExecuteActionButton.bind(this),
            afterExecuteAction: this.afterExecuteActionButton.bind(this),
            reload: () => this.model.load(),
        });

        useEffect(
            () => {
                this.onSelectionChanged();
            },
            () => [this.selectionKey, this.model.root.isDomainSelected],
        );

        this.exportRecords = useExportRecords(this.env, () =>
            this.getExportableFields(),
        );
        this.deleteRecordsWithConfirmation = useDeleteRecords(this.model);
    }

    get actionMenuProps() {
        return {
            getActiveIds: () =>
                this.model.root.selection.map((/** @type {any} */ r) => r.resId),
            context: this.model.root.context,
            domain: this.props.domain,
            items: this.actionMenuItems,
            isDomainSelected: this.model.root.isDomainSelected,
            resModel: this.model.root.resModel,
            onActionExecuted: (/** @type {any} */ { noReload } = {}) => {
                if (!noReload) {
                    return this.model.load();
                }
            },
        };
    }

    /**
     * @param {Record<string, any>} button a parsed `<header>` button
     * @returns {Record<string, any>}
     */
    headerButtonProps(button) {
        return {
            list: this.model.root,
            className: button.className,
            clickParams: button.clickParams,
            defaultRank: "btn-secondary",
            domain: this.props.domain,
            icon: button.icon,
            string: button.string,
            title: button.title,
            attrs: button.attrs,
            modifiers: button.modifiers,
        };
    }

    get chassisProps() {
        return {
            ...this.chassis.props,
            className: this.className,
            autofocusSearchBar: this.firstLoad,
            showSearchBarToggler: !this.hasSelectedRecords,
        };
    }

    get display() {
        const { controlPanel } = this.props.display;
        if (!controlPanel) {
            return this.props.display;
        }
        return {
            ...this.props.display,
            controlPanel: {
                ...controlPanel,
                layoutActions: !this.hasSelectedRecords,
            },
        };
    }

    /** @returns {string} */
    get selectionKey() {
        const selection = this.model.root.selection;
        if (!selection?.length) {
            return "";
        }
        return selection.map((/** @type {any} */ record) => record.id).join(",");
    }

    get hasSelectedRecords() {
        return this.model.root.selection?.length > 0 || this.isDomainSelected;
    }

    get isDomainSelected() {
        return this.model.root.isDomainSelected;
    }

    get modelOptions() {
        return computeModelOptions(this.env, this.props.display);
    }

    getStaticActionMenuItems() {
        return prepareStaticActionMenuItems({
            export: {
                isAvailable: () => this.isExportEnable,
                callback: () => this.exportRecords(),
            },
            duplicate: {
                isAvailable: () => this.archInfo.activeActions.duplicate,
                callback: () => this.model.root.duplicateRecords(),
            },
            archive: {
                isAvailable: () => this.archiveEnabled,
                callback: () =>
                    this.model.root.toggleArchiveWithConfirmation(
                        true,
                        this.archiveDialogProps,
                    ),
            },
            unarchive: {
                isAvailable: () => this.archiveEnabled,
                callback: () => this.model.root.toggleArchiveWithConfirmation(false),
            },
            delete: {
                isAvailable: () => this.archInfo.activeActions.delete,
                callback: () => this.onDeleteSelectedRecords(),
            },
        });
    }

    /** @returns {any[]} */
    getExportableFields() {
        return [];
    }

    async onSelectionChanged() {
        log.logic("onSelectionChanged", () => ({
            selected: this.model.root.selection?.length,
            domainSelected: this.model.root.isDomainSelected,
            forwarded: Boolean(this.props.onSelectionChanged),
        }));
        if (!this.props.onSelectionChanged) {
            return;
        }
        let resIds;
        try {
            resIds = await this._selectionLoads.add(this.model.root.getResIds(true));
        } catch (error) {
            if (error instanceof SupersededError) {
                return;
            }
            throw error;
        }
        this.props.onSelectionChanged(resIds);
    }

    get scrollSelector() {
        return ".o_content";
    }

    setupPager() {
        usePager(() => {
            const root = this.model.root;
            if (this.model.useSampleModel || !this.pagerEnabled(root)) {
                return;
            }
            const { count, hasLimitedCount, isGrouped, limit, offset } = root;
            return {
                offset,
                limit,
                total: count,
                onUpdate: async ({ offset, limit }, hasNavigated) => {
                    log.logic("pager", () => ({
                        offset,
                        limit,
                        hasNavigated,
                        total: root.count,
                    }));
                    if (!(await this.beforePagerUpdate())) {
                        return;
                    }
                    await root.load({ limit, offset });
                    await this.onUpdatedPager();
                    if (hasNavigated) {
                        this.onPageChangeScroll();
                    }
                },
                updateTotal:
                    !isGrouped && hasLimitedCount ? () => root.fetchCount() : undefined,
            };
        });
    }

    /** @param {any} _root */
    pagerEnabled(_root) {
        return true;
    }

    /** @returns {Promise<boolean>} false keeps the current page */
    async beforePagerUpdate() {
        return true;
    }

    async onUpdatedPager() {}

    onPageChangeScroll() {
        if (!this.rootRef?.el) {
            return;
        }
        if (this.env.isSmall) {
            this.rootRef.el.scrollTop = 0;
        } else {
            const el = this.rootRef.el.querySelector(this.scrollSelector);
            if (el) {
                el.scrollTop = 0;
            }
        }
    }

    onDeleteSelectedRecords() {
        this.deleteRecordsWithConfirmation(this.deleteConfirmationDialogProps);
    }
}
