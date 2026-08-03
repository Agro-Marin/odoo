// @ts-check
/** @odoo-module native */

/** @module @web/views/multi_record_controller */

import {
    Component,
    onMounted,
    onWillStart,
    useEffect,
    useRef,
    useSubEnv,
} from "@odoo/owl";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";
import { useSearchBarToggler } from "@web/search/search_bar/search_bar_toggler";
import { useViewButtons } from "@web/views/view_button/view_button_hook";
import { useDeleteRecords, useExportRecords } from "@web/views/view_hook";
import {
    buildActionMenuItems,
    computeArchiveEnabled,
    computeModelOptions,
    useControllerServices,
} from "@web/views/view_utils";

export class MultiRecordController extends Component {
    /** @type {any} */
    model;

    /** @type {any} */
    actionService;
    /** @type {any} */
    dialogService;
    /** @type {any} */
    notification;
    /** @type {any} */
    orm;
    /** @type {any} */
    _uiHooks;
    /** @type {any} */
    archInfo;
    /** @type {import("@odoo/owl").Ref<HTMLElement>} */
    rootRef;
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
    /** @type {number} */
    _selectionEpoch = 0;

    setup() {
        const { action, dialog, notification, orm, uiHooks } = useControllerServices();
        this.actionService = action;
        this.dialogService = dialog;
        this.notification = notification;
        this.orm = orm;
        this._uiHooks = uiHooks;

        this.archInfo = this.props.archInfo;
        this.rootRef = useRef("root");

        this.archiveEnabled = computeArchiveEnabled(this.props.fields);
        this.searchBarToggler = useSearchBarToggler();
        this.firstLoad = true;
        onMounted(() => {
            this.firstLoad = false;
        });
    }

    initMultiRecordBehavior() {
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

    get actionMenuItems() {
        return buildActionMenuItems(
            this.getStaticActionMenuItems(),
            this.props.info.actionMenus,
        );
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

    get archiveDialogProps() {
        return {};
    }

    get deleteConfirmationDialogProps() {
        return {};
    }

    getStaticActionMenuItems() {
        return {
            export: {
                isAvailable: () => this.isExportEnable,
                sequence: 10,
                icon: "fa-solid fa-upload",
                description: _t("Export"),
                callback: () => this.exportRecords(),
            },
            duplicate: {
                isAvailable: () => this.archInfo.activeActions.duplicate,
                sequence: 30,
                icon: "fa-regular fa-clone",
                description: _t("Duplicate"),
                callback: () => this.model.root.duplicateRecords(),
            },
            archive: {
                isAvailable: () => this.archiveEnabled,
                sequence: 40,
                icon: "oi oi-archive",
                description: _t("Archive"),
                callback: () =>
                    this.model.root.toggleArchiveWithConfirmation(
                        true,
                        this.archiveDialogProps,
                    ),
            },
            unarchive: {
                isAvailable: () => this.archiveEnabled,
                sequence: 45,
                icon: "oi oi-unarchive",
                description: _t("Unarchive"),
                callback: () => this.model.root.toggleArchiveWithConfirmation(false),
            },
            delete: {
                isAvailable: () => this.archInfo.activeActions.delete,
                sequence: 50,
                icon: "fa-regular fa-trash-can",
                description: _t("Delete"),
                class: "text-danger",
                callback: () => this.onDeleteSelectedRecords(),
            },
        };
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
        const epoch = ++this._selectionEpoch;
        const resIds = await this.model.root.getResIds(true);
        if (epoch !== this._selectionEpoch) {
            return;
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

    /**
     * @param {any} clickParams
     * @returns {Promise<boolean | void>}
     */
    async beforeExecuteActionButton(clickParams) {}

    /**
     * @param {any} clickParams
     */
    async afterExecuteActionButton(clickParams) {}
}
