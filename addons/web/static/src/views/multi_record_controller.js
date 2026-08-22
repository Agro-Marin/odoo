// @ts-check
/** @odoo-module native */

import { onMounted, onWillStart, useEffect, useSubEnv } from "@odoo/owl";
import { user } from "@web/core/user";
import { KeepLast, SupersededError } from "@web/core/utils/concurrency";
import { useSearchBarToggler } from "@web/search/search_bar/search_bar_toggler";
import { useViewButtons } from "@web/views/view_button/view_button_hook";
import { ViewController } from "@web/views/view_controller";
import { useDeleteRecords, useExportRecords } from "@web/views/view_hook";
import {
    buildStaticActionMenuItems,
    computeArchiveEnabled,
    computeModelOptions,
} from "@web/views/view_utils";

export class MultiRecordController extends ViewController {
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
        this.searchBarToggler = useSearchBarToggler();
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

    /**
     * @returns {string}
     */
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
        return buildStaticActionMenuItems({
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

    /**
     * @returns {any[]}
     */
    getExportableFields() {
        return [];
    }

    async onSelectionChanged() {
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
