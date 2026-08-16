// @ts-check
/** @odoo-module native */

/** @module @web/views/form/form_controller */

import {
    Component,
    onError,
    onMounted,
    onRendered,
    status,
    useEffect,
    useRef,
    useState,
    useSubEnv,
} from "@odoo/owl";
import { useSetupAction } from "@web/core/action_hook";
import { hasTouch } from "@web/core/browser/feature_detection";
import { useDebugCategory } from "@web/core/debug/debug_context";
import { AppEvent, ModelEvent } from "@web/core/events";
import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { _t } from "@web/core/translation";
import { createElement } from "@web/core/utils/dom/xml";
import { useBus, useService } from "@web/core/utils/hooks";
import { effect } from "@web/core/utils/reactive";
import { Field } from "@web/fields/field";
import { useModel } from "@web/model/model";
import { FetchRecordError } from "@web/model/relational_model/errors";
import {
    addFieldDependencies,
    extractFieldsFromArchInfo,
} from "@web/model/relational_model/utils";
import { Layout } from "@web/search/layout";
import { usePager } from "@web/search/pager_hook";
import { ConfirmationDialog } from "@web/ui/dialog/confirmation_dialog";
import { SIZES } from "@web/ui/viewport";
import { standardViewProps } from "@web/views/standard_view_props";
import { ViewButton } from "@web/views/view_button/view_button";
import {
    executeButtonCallback,
    useViewButtons,
} from "@web/views/view_button/view_button_hook";
import { useViewCompiler } from "@web/views/view_compiler";
import { useDeleteRecords } from "@web/views/view_hook";
import {
    buildActionMenuItems,
    computeArchiveEnabled,
    handleBeforeUnload,
    useControllerServices,
} from "@web/views/view_utils";
import { Widget } from "@web/views/widgets/widget";

import { ButtonBox } from "./button_box/button_box.js";
import { FormCogMenu } from "./form_cog_menu/form_cog_menu.js";
import { FormCompiler } from "./form_compiler.js";
import { FormErrorDialog } from "./form_error_dialog/form_error_dialog.js";
import { FormSaveCoordinator } from "./form_save_coordinator.js";
import { FormStatusIndicator } from "./form_status_indicator/form_status_indicator.js";
import { loadSubViews, useFormViewInDialog } from "./form_utils.js";

/**
 * @type {WeakMap<object, { footerArchInfo: object, strippedArchInfo: object }>}
 */
const footerArchInfoCache = new WeakMap();

export class FormController extends Component {
    static template = `web.FormView`;
    static components = {
        FormStatusIndicator,
        Layout,
        ButtonBox,
        ViewButton,
        Field,
        CogMenu: FormCogMenu,
        Widget,
    };

    static props = {
        ...standardViewProps,
        discardRecord: { type: Function, optional: true },
        readonly: { type: Boolean, optional: true },
        saveRecord: { type: Function, optional: true },
        removeRecord: { type: Function, optional: true },
        Model: Function,
        Renderer: Function,
        Compiler: Function,
        archInfo: Object,
        buttonTemplate: String,
        preventCreate: { type: Boolean, optional: true },
        preventEdit: { type: Boolean, optional: true },
        onDiscard: { type: Function, optional: true },
        onSave: { type: Function, optional: true },
    };
    static defaultProps = {
        preventCreate: false,
        preventEdit: false,
        updateActionState: () => {},
    };

    /** @type {import("@web/core/action_port").ActionPort} */
    actionService;
    /** @type {import("services").ServiceFactories["dialog"]} */
    dialogService;
    /** @type {import("services").ServiceFactories["orm"]} */
    orm;
    /** @type {any} */
    ui;
    /** @type {any} */
    multiCompanyRecovery;
    /** @type {any} */
    formDialogStack;
    /** @type {any} */
    duplicateId;
    /** @type {any} */
    onWillDisplayOnchangeWarning;
    /** @type {any} */
    model;
    /** @type {any} */
    saveCoordinator;
    /** @type {import("@odoo/owl").Ref<HTMLElement>} */
    rootRef;
    /** @type {any} */
    deleteRecordsWithConfirmation;

    setup() {
        this.evaluateBooleanExpr = evaluateBooleanExpr;
        const { action, dialog, notification, orm, uiHooks } = useControllerServices();
        this.actionService = action;
        this.dialogService = dialog;
        this.notification = notification;
        this.orm = orm;
        this._uiHooks = uiHooks;
        this.viewService = useService("view");
        this.ui = useService("ui");
        this.multiCompanyRecovery = useService("multi_company_recovery");
        this.formDialogStack = useService("form_dialog_stack");
        useBus(this.ui.bus, AppEvent.RESIZE, /** @type {any} */ (this.render));

        this.archInfo = this.props.archInfo;
        const { create, edit } = this.archInfo.activeActions;
        this.canCreate = create && !this.props.preventCreate;
        this.canEdit = edit && !this.props.preventEdit;
        this.duplicateId = false;

        this.display = { ...this.props.display };
        if (this.env.inDialog) {
            this.display.controlPanel = false;
        }

        const mountedProm = new Promise((r) => onMounted(/** @type {any} */ (r)));
        this.onWillDisplayOnchangeWarning = () => mountedProm;

        const beforeFirstLoad = async () => {
            await loadSubViews(
                this.archInfo.fieldNodes,
                this.props.fields,
                this.props.context,
                this.props.resModel,
                this.viewService,
                this.env.isSmall,
            );
            const { activeFields, fields } = extractFieldsFromArchInfo(
                this.archInfo,
                this.props.fields,
            );
            if (this.display.controlPanel) {
                addFieldDependencies(activeFields, fields, [
                    { name: "display_name", type: "char", readonly: true },
                ]);
            }
            this.model.config.activeFields = activeFields;
            this.model.config.fields = fields;
        };
        this.model = useState(
            useModel(this.props.Model, this.modelParams, { beforeFirstLoad }),
        );
        this.saveCoordinator = useState(
            new FormSaveCoordinator(this.model, {
                onSaveError: (error, callbacks) =>
                    this._renderSaveErrorDialog(error, callbacks),
                onUrgentSaveFailed: () => this._onUrgentSaveFailed(),
                recoverFromSaveError: (error, model) =>
                    this.multiCompanyRecovery.recoverFromSaveError(error, model),
            }),
        );
        useSubEnv({ model: this.model });
        onMounted(() => {
            effect(
                (model) => {
                    if (status(this) === "mounted") {
                        this.props.updateActionState({
                            resId: model.root.resId,
                        });
                    }
                },
                [this.model],
            );
        });

        onError((error) => {
            if (
                this.multiCompanyRecovery.recoverFromLifecycleError(error, {
                    inDialog: this.env.inDialog,
                    env: /** @type {import("@web/env").OdooEnv} */ (this.env),
                })
            ) {
                return;
            }
            throw error;
        });

        if (this.archInfo.xmlDoc.querySelector("footer:not(field footer)")) {
            let cached = footerArchInfoCache.get(this.props.archInfo);
            if (!cached) {
                const xmlDoc = this.archInfo.xmlDoc.cloneNode(true);
                const footerArchInfo = { ...this.archInfo };
                footerArchInfo.xmlDoc = createElement("t");
                for (const footer of xmlDoc.querySelectorAll(
                    "footer:not(field footer)",
                )) {
                    footerArchInfo.xmlDoc.append(footer);
                }
                footerArchInfo.arch = footerArchInfo.xmlDoc.outerHTML;
                cached = {
                    footerArchInfo,
                    strippedArchInfo: {
                        ...this.archInfo,
                        xmlDoc,
                        arch: xmlDoc.outerHTML,
                    },
                };
                footerArchInfoCache.set(this.props.archInfo, cached);
            }
            this.footerArchInfo = cached.footerArchInfo;
            this.archInfo = cached.strippedArchInfo;
        }

        const xmlDocButtonBox = this.archInfo.xmlDoc.querySelector(
            "div[name='button_box']:not(field div)",
        );
        if (xmlDocButtonBox) {
            const buttonBoxTemplates = useViewCompiler(
                this.props.Compiler || FormCompiler,
                { ButtonBox: xmlDocButtonBox },
                { isSubView: true },
            );
            this.buttonBoxTemplate = buttonBoxTemplates.ButtonBox;
        }

        this.rootRef = useRef("root");
        useViewButtons(this.rootRef, {
            beforeExecuteAction: this.beforeExecuteActionButton.bind(this),
            afterExecuteAction: this.afterExecuteActionButton.bind(this),
            reload: () => this.model.load(),
        });

        const state = this.props.state || {};
        const activeNotebookPages = { ...state.activeNotebookPages };
        this.onNotebookPageChange = (notebookId, page) => {
            if (page) {
                activeNotebookPages[notebookId] = page;
            }
        };

        useSetupAction({
            rootRef: this.rootRef,
            beforeVisibilityChange: () => this.beforeVisibilityChange(),
            beforeLeave: (options) => this.beforeLeave(options),
            beforeUnload: (ev) => this.beforeUnload(ev),
            getLocalState: () => ({
                activeNotebookPages: !this.model.root.isNew ? activeNotebookPages : {},
                modelState: /** @type {any} */ (this.model).exportState(),
                resId: this.model.root.resId,
            }),
        });
        useDebugCategory("form", { component: this });

        usePager(() => {
            if (!this.model.root.isNew) {
                const resIds = this.model.root.resIds;
                return {
                    offset: resIds.indexOf(this.model.root.resId),
                    limit: 1,
                    total: resIds.length,
                    onUpdate: ({ offset }) => this.onPagerUpdate({ offset, resIds }),
                };
            }
        });

        onRendered(() => {
            this.env.config.setDisplayName(this.displayName());
        });

        const { disableAutofocus } = this.archInfo;
        if (!disableAutofocus) {
            useEffect(
                (isInEdition) => {
                    if (
                        !isInEdition &&
                        !this.rootRef.el
                            ?.querySelector(".o_content")
                            ?.contains(document.activeElement)
                    ) {
                        const elementToFocus = this.rootRef.el?.querySelector(
                            ".o_content button.btn-primary",
                        );
                        if (elementToFocus) {
                            elementToFocus.focus();
                        }
                    }
                },
                () => [this.model.root.isInEdition],
            );
        }

        if (this.env.inDialog) {
            useFormViewInDialog();
        }

        this.deleteRecordsWithConfirmation = useDeleteRecords(this.model);
    }

    get cogMenuProps() {
        return {
            getActiveIds: () => (this.model.root.isNew ? [] : [this.model.root.resId]),
            context: this.model.root.context,
            items: this.props.info.actionMenus ? this.actionMenuItems : {},
            isDomainSelected: this.model.root.isDomainSelected,
            resModel: this.model.root.resModel,
            domain: this.props.domain,
            onActionExecuted: (
                /** @type {{ noReload?: boolean }} */ { noReload } = {},
            ) => {
                if (!noReload) {
                    const { resId, resIds } = this.model.root;
                    return this.model.load({ resId: resId, resIds: resIds });
                }
            },
            shouldExecuteAction: this.shouldExecuteAction.bind(this),
        };
    }

    get modelParams() {
        return {
            config: {
                resModel: this.props.resModel,
                resId: this.props.resId || false,
                resIds:
                    this.props.resIds || (this.props.resId ? [this.props.resId] : []),
                fields: this.props.fields,
                activeFields: {},
                isMonoRecord: true,
                mode: this.props.readonly ? "readonly" : "edit",
                context: this.props.context,
            },
            state: this.props.state?.modelState,
            hooks: {
                lifecycle: {
                    onWillLoadRoot: this.onWillLoadRoot.bind(this),
                    onWillSaveRecord: this.onWillSaveRecord.bind(this),
                    onRecordSaved: this.onRecordSaved.bind(this),
                    onWillDisplayOnchangeWarning:
                        this.onWillDisplayOnchangeWarning.bind(this),
                },
                ui: this._uiHooks,
            },
            useSendBeaconToSaveUrgently: true,
        };
    }

    onWillLoadRoot() {
        this.duplicateId = undefined;
    }

    /**
     * @param {any} record
     */
    async onRecordSaved(record, changes) {
        if (this.duplicateId === record.id) {
            const translationChanges = {};
            for (const fieldName of Object.keys(changes)) {
                if (record.fields[fieldName].translate) {
                    translationChanges[fieldName] = changes[fieldName];
                }
            }
            if (Object.keys(translationChanges).length) {
                await this.orm.call(
                    this.model.root.resModel,
                    "web_override_translations",
                    [[this.model.root.resId], translationChanges],
                );
            }
        }
    }

    async onWillSaveRecord() {}

    /**
     * @param {Object} error
     * @param {{ discard: Function, retry: Function }} callbacks
     * @returns {Promise<boolean>}
     */
    _renderSaveErrorDialog(error, { discard, retry }) {
        return new Promise((resolve) => {
            this.dialogService.add(FormErrorDialog, {
                message: error.data.message,
                data: error.data,
                onDiscard: () => {
                    discard();
                    resolve(true);
                },
                onRedirect: async ({ action, additionalContext }) => {
                    try {
                        await this.actionService.doAction(action, {
                            additionalContext,
                            forceLeave: true,
                        });
                    } finally {
                        resolve(false);
                    }
                },
                onStayHere: () => resolve(false),
            });
        });
    }

    _onUrgentSaveFailed() {}

    /** @returns {string} */
    displayName() {
        const displayName = this.model.root.data.display_name;
        if (displayName) {
            return displayName;
        }
        return (this.model.root.isNew && _t("New")) || "";
    }

    /**
     * @param {{ offset: number, resIds: number[] }} params
     */
    async onPagerUpdate({ offset, resIds }) {
        const nextId = resIds[offset];
        try {
            const isDirty = await this.model.root.isDirty();
            if (isDirty) {
                await this.saveCoordinator.requestSave({ nextId });
            } else {
                await this.model.load({ resId: nextId });
            }
        } catch (e) {
            if (e instanceof FetchRecordError) {
                await this.model.load({
                    resIds: this.model.config.resIds.filter(
                        (id) => !e.resIds.includes(id),
                    ),
                });
            }
            throw e;
        }
    }

    async beforeVisibilityChange() {
        if (
            document.visibilityState !== "hidden" ||
            !this.formDialogStack.isEmpty ||
            this.model.root.isNew
        ) {
            return;
        }
        // requestSave() in "silent" mode reports failure by RESOLVING to false —
        // it does not reject — so the outcome has to be read from the return
        // value. Chaining .catch() here would never run and the record would be
        // left dirty with no signal at all.
        let saved;
        try {
            saved = await this.saveCoordinator.requestSave({
                errorMode: "silent",
                checkDirty: true,
            });
        } catch (error) {
            this.onAutoSaveFailed(error);
            return;
        }
        if (saved === false) {
            this.onAutoSaveFailed(this.saveCoordinator.lastError);
        }
    }

    /**
     * The tab is hidden, so a dialog would be pointless and a notification is
     * queued behind the user's return. Keep the record dirty (the normal
     * unsaved-changes guards still apply) and leave a diagnostic trail.
     *
     * @param {any} [error]
     */
    onAutoSaveFailed(error) {
        console.warn("Auto-save on tab switch failed:", error);
    }

    /** @param {{ forceLeave?: boolean }} [options] */
    async beforeLeave({ forceLeave } = {}) {
        if (forceLeave) {
            return;
        }
        if (!(await this.model.root.isDirty())) {
            return true;
        }
        const saved = await this.saveCoordinator.requestSave({
            reload: false,
            saveOverride: this.props.saveRecord,
        });
        if (saved && this.props.onSave) {
            this.props.onSave(this.model.root, { reload: false });
        }
        return saved;
    }

    beforeUnload(ev) {
        return handleBeforeUnload(ev, {
            record: this.model.root,
            inDialog: this.env.inDialog,
            useSendBeacon: this.model.useSendBeaconToSaveUrgently,
            urgentSave: () => this.saveCoordinator.requestUrgentSave(),
        });
    }

    getStaticActionMenuItems() {
        const { activeActions } = this.archInfo;
        return {
            addPropertyFieldValue: {
                isAvailable: () => activeActions.addPropertyFieldValue,
                sequence: 10,
                icon: "fa-solid fa-cogs",
                description: _t("Edit Properties"),
                callback: () => this.model.bus.trigger(ModelEvent.PROPERTY_FIELD_EDIT),
            },
            duplicate: {
                isAvailable: () => activeActions.create && activeActions.duplicate,
                sequence: 30,
                icon: "fa-regular fa-clone",
                description: _t("Duplicate"),
                callback: () => this.duplicateRecord(),
            },
            archive: {
                isAvailable: () => this.archiveEnabled && this.model.root.isActive,
                sequence: 40,
                description: _t("Archive"),
                icon: "oi oi-archive",
                callback: () => {
                    this.dialogService.add(ConfirmationDialog, this.archiveDialogProps);
                },
            },
            unarchive: {
                isAvailable: () => this.archiveEnabled && !this.model.root.isActive,
                sequence: 45,
                icon: "oi oi-unarchive",
                description: _t("Unarchive"),
                callback: () => this.model.root.unarchive(),
            },
            delete: {
                isAvailable: () => activeActions.delete && !this.model.root.isNew,
                sequence: 50,
                icon: "fa-regular fa-trash-can",
                description: _t("Delete"),
                class: "text-danger",
                callback: () => this.deleteRecord(),
                skipSave: true,
            },
        };
    }

    get archiveDialogProps() {
        return {
            body: _t("Are you sure that you want to archive this record?"),
            confirmLabel: _t("Archive"),
            confirm: () => this.model.root.archive(),
            cancel: () => {},
        };
    }

    get actionMenuItems() {
        return buildActionMenuItems(
            this.getStaticActionMenuItems(),
            this.props.info.actionMenus,
        );
    }

    get archiveEnabled() {
        return computeArchiveEnabled(this.props.fields, {
            presentIn: this.model.root.activeFields,
        });
    }

    async shouldExecuteAction(item) {
        const dirty = await this.model.root.isDirty();
        if ((dirty || this.model.root.isNew) && !item.skipSave) {
            const saved = await this.saveCoordinator.requestSave();
            // A record still new after a truthy save means the save was
            // resolved by the error dialog's "Discard changes": nothing was
            // persisted, so there is no record to run the action on.
            return (
                saved !== false &&
                !this.saveCoordinator.lastError &&
                !this.model.root.isNew
            );
        }
        return true;
    }

    async duplicateRecord() {
        await this.model.root.duplicate();
        this.duplicateId = this.model.root.id;
    }

    get deleteConfirmationDialogProps() {
        return {
            confirm: async () => {
                await this.model.root.delete();
                if (!this.model.root.resId) {
                    this.env.config.historyBack();
                }
            },
        };
    }

    deleteRecord() {
        this.deleteRecordsWithConfirmation(this.deleteConfirmationDialogProps, [
            this.model.root,
        ]);
    }

    async beforeExecuteActionButton(clickParams) {
        const record = this.model.root;
        if (clickParams.special !== "cancel") {
            let saved;
            if (clickParams.special === "save" && this.props.saveRecord) {
                saved = await this.saveCoordinator.requestSave({
                    saveOverride: (r) => this.props.saveRecord(r, clickParams),
                    errorMode: "rethrow",
                });
            } else {
                saved = await this.saveCoordinator.requestSave({
                    reload: !(this.env.inDialog && clickParams.close),
                    errorMode: "rethrow",
                });
            }
            if (saved !== false && this.props.onSave) {
                this.props.onSave(record, clickParams);
            }
            return saved;
        } else if (this.props.onDiscard) {
            this.props.onDiscard(record);
        }
    }

    async afterExecuteActionButton(clickParams) {}

    async create() {
        const canProceed = await this.saveCoordinator.requestSave({
            checkDirty: true,
        });
        if (canProceed) {
            await executeButtonCallback(
                /** @type {any} */ (this.ui.activeElement),
                () => this.model.load({ resId: false }),
            );
        }
    }

    /**
     * @param {Object} [params]
     * @returns {Promise<boolean>}
     */
    async save(params) {
        const record = this.model.root;
        const saved = await this.saveCoordinator.requestSave({
            saveOverride: this.props.saveRecord,
            errorMode: "rethrow",
            params,
        });
        if (saved && this.props.onSave) {
            this.props.onSave(record, params);
        }
        return saved;
    }

    saveButtonClicked(params = {}) {
        return executeButtonCallback(/** @type {any} */ (this.ui.activeElement), () =>
            this.save(params),
        );
    }

    async discard() {
        if (this.props.discardRecord) {
            this.props.discardRecord(this.model.root);
            return;
        }
        await this.saveCoordinator.requestDiscard();
        if (this.props.onDiscard) {
            this.props.onDiscard(this.model.root);
        }
        if (this.env.inDialog) {
            await this.env.dialogData.close();
        } else if (this.model.root.isNew) {
            this.env.config.historyBack();
        }
    }

    get className() {
        const result = {};
        const { size } = this.ui;
        if (size <= SIZES.XS) {
            result.o_xxs_form_view = true;
        } else if (!this.env.inDialog && size === SIZES.XXL) {
            result["o_xxl_form_view h-100"] = true;
        }
        if (this.props.className) {
            result[this.props.className] = true;
        }
        result["o_field_highlight"] = size < SIZES.SM || hasTouch();
        return result;
    }
}
