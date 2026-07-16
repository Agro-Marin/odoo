// @ts-check
/** @odoo-module native */

/** @module @web/views/form/form_controller - Form view lifecycle: record save, discard, duplicate, archive, pager navigation, and error recovery */

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
import { AppEvent, ModelEvent } from "@web/core/events";
import { _t } from "@web/core/l10n/translation";
import { evaluateBooleanExpr } from "@web/core/py_js/py";
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
import { useDebugCategory } from "@web/services/debug/debug_context";
import { SIZES } from "@web/ui/block/ui_service";
import { ConfirmationDialog } from "@web/ui/dialog/confirmation_dialog";
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
 * Per-``props.archInfo`` memo of the footer-stripped arch clone (+ the extracted
 * footer arch). Keyed by the shared arch object's identity so repeated
 * controller instantiations with identical props reuse the SAME stripped
 * Element, letting the view compiler's Element-keyed ``archKeyCache`` hit
 * instead of re-serializing the arch on every dialog open.
 * @type {WeakMap<object, { footerArchInfo: object, strippedArchInfo: object }>}
 */
const footerArchInfoCache = new WeakMap();

/**
 * Controller for the form view.
 *
 * Manages a single record: loading, saving, discarding, duplicating, archiving,
 * deleting, pager navigation, and error recovery (including company-switching
 * on AccessError). Sub-views for x2many fields are loaded on first render.
 */
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

        // Wait until mounted to show onchange warnings: avoids a double-show if the
        // component is destroyed/recreated first, and avoids an infinite loop for
        // form views in dialogs (willStart calling dialog.add).
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
        // Centralizes the 9 historical save-related entry points
        // (onPagerUpdate / beforeVisibilityChange / beforeLeave /
        // beforeUnload / shouldExecuteAction / beforeExecuteActionButton /
        // create / save / saveButtonClicked) into one observable surface.
        // See ``form_save_coordinator.js`` for the full rationale and the
        // public API.
        this.saveCoordinator = useState(
            new FormSaveCoordinator(this.model, {
                onSaveError: (error, callbacks) =>
                    this._renderSaveErrorDialog(error, callbacks),
                // No pre/post-save hooks here: pre-save vetoes belong to the
                // model-level ``onWillSaveRecord`` hook (fires after validation,
                // before web_save — a coordinator hook would double-fire and
                // run pre-validation). Post-save ``props.onSave`` is invoked
                // explicitly by the 4 call sites that historically called it
                // (beforeLeave, beforeExecuteActionButton, save,
                // saveButtonClicked), not by every requestSave. The old unwired
                // onWillSave/onSaved hooks here were removed as dead code.
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

        // select footers that are not in subviews and move them to another arch
        // that will be moved to the dialog's footer (if we are in a dialog)
        if (this.archInfo.xmlDoc.querySelector("footer:not(field footer)")) {
            // Work on clones: the shared props.archInfo (and its xmlDoc) must
            // stay untouched — it can feed another controller instantiation
            // (remount with identical props, error-recovery re-render), which
            // would otherwise find its footers already stripped. The
            // controller keeps its own footer-less copy on this.archInfo.
            //
            // Memoize the footer-stripped clone per props.archInfo: a fresh
            // clone is a brand-new Element, so ``useViewCompiler``'s
            // ``archKeyCache`` (WeakMap keyed by Element identity) would miss
            // and re-serialize + recompile the whole arch on every dialog open.
            // The clone is only mutated once (footers moved out during this
            // block) and thereafter read-only (compiled by value), so it is
            // safe to share the same stripped Element across instantiations.
            let cached = footerArchInfoCache.get(this.props.archInfo);
            if (!cached) {
                const xmlDoc = this.archInfo.xmlDoc.cloneNode(true);
                const footerArchInfo = { ...this.archInfo };
                footerArchInfo.xmlDoc = createElement("t");
                for (const footer of xmlDoc.querySelectorAll(
                    "footer:not(field footer)",
                )) {
                    // append() moves the node out of the cloned doc
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
                activeFields: {}, // will be generated after loading sub views (see willStart)
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

    /**
     * Called before (re)loading the root record datapoint. ``this.model.root``
     * may not exist yet at this point, if this is the first load.
     */
    onWillLoadRoot() {
        this.duplicateId = undefined;
    }

    /**
     * Called after a successful save; skipped if the record was invalid, a
     * server error was thrown, or there were no changes to save.
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

    /**
     * Called before saving the record, if it is valid. Returning false
     * prevents the save.
     */
    async onWillSaveRecord() {}

    /**
     * Render the save-error dialog UX (``FormErrorDialog`` with discard /
     * redirect / stay choices). Wired into the coordinator's ``onSaveError``
     * hook; called only when ``recoverFromSaveError`` already returned false.
     *
     * Contract: ``error.data`` (an ``RPCError``) is always present —
     * payload-less errors (``ConnectionLostError``, timeouts) are rethrown
     * earlier by the coordinator's dialog-mode ``onError`` (see
     * ``_buildOnError``) and never reach here.
     *
     * Historical: replaces the old tri-mode ``onSaveError(error, opts,
     * showErrorDialog)``, whose semantics drifted across 5+ call sites
     * (renamed 2026-05); the coordinator now owns dispatch, so this method
     * is single-purpose.
     *
     * @param {Object} error - the RPC error
     * @param {{ discard: Function, retry: Function }} callbacks
     * @returns {Promise<boolean>} true if user chose discard (caller may
     *     proceed); false if user chose redirect or stay (caller blocks)
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

    /**
     * Coordinator hook: invoked when the urgent (sendBeacon) save path
     * fails — typically because the payload exceeded the browser's
     * sendBeacon budget.  The caller (``beforeUnload``) is also informed
     * via the false return value of ``requestUrgentSave``, so it can
     * ``ev.preventDefault()`` on the unload event.  No-op here for now;
     * left as an extension point for future telemetry / notifications.
     */
    _onUrgentSaveFailed() {}

    /** @returns {string} the display name for the breadcrumb (record name or "New") */
    displayName() {
        const displayName = this.model.root.data.display_name;
        if (displayName) {
            return displayName;
        }
        return (this.model.root.isNew && _t("New")) || "";
    }

    /**
     * Navigate to a different record via the pager. Saves dirty records first.
     *
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
                // await the recovery load before rethrowing, to avoid an
                // unhandled rejection interleaving with subsequent loads
                await this.model.load({
                    resIds: this.model.config.resIds.filter(
                        (id) => !e.resIds.includes(id),
                    ),
                });
            }
            throw e;
        }
    }

    beforeVisibilityChange() {
        if (
            document.visibilityState === "hidden" &&
            this.formDialogStack.isEmpty &&
            !this.model.root.isNew
        ) {
            // checkDirty: a clean record must short-circuit BEFORE the save
            // pipeline runs — without it, every tab-hide on a dirty-but-
            // invalid record re-fires the "Missing required fields" toast
            // and churns the status indicator through saving→clean.
            return this.saveCoordinator
                .requestSave({ errorMode: "silent", checkDirty: true })
                .catch((e) => console.warn("Auto-save on tab switch failed:", e));
        }
    }

    /** @param {{ forceLeave?: boolean }} [options] */
    async beforeLeave({ forceLeave } = {}) {
        if (forceLeave) {
            return;
        }
        if (!(await this.model.root.isDirty())) {
            // Nothing to save. Hoisted out of the coordinator (instead of
            // ``checkDirty: true``) because that short-circuit resolves
            // ``true`` and would fire ``props.onSave`` below: embedders hang
            // "record persisted" side effects on it (e.g. stock_barcode
            // closes its line-edit pane), which must not run on a clean
            // leave.
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
        const record = this.model.root;
        // A record is beacon-eligible only when it already exists (sendBeacon
        // cannot return the new id for a creation), is not inside a dialog, and
        // the model opted into sendBeacon urgent saves. Only that path reaches
        // navigator.sendBeacon() synchronously and settles in microtasks, so a
        // late ``ev.preventDefault()`` after awaiting is still honored.
        const canBeacon =
            Boolean(record.resId) &&
            !this.env.inDialog &&
            this.model.useSendBeaconToSaveUrgently;
        if (!canBeacon) {
            // Non-beaconable record (a dirty NEW/creation record, or a dialog
            // form): the urgent save would ``await`` a real web_save macrotask,
            // so ``ev.preventDefault()`` would land after the synchronous
            // beforeunload dispatch has already returned — too late for the
            // browser to honor it — while the in-flight fetch is aborted by the
            // navigation, silently losing the user's work. Block the unload
            // SYNCHRONOUSLY instead (preventDefault BEFORE any await) so the
            // browser shows its native "unsaved changes" prompt while the record
            // is still dirty and the user can save manually.
            if (record.dirty) {
                ev.preventDefault();
                ev.returnValue = "Unsaved changes";
            }
            return;
        }
        return this.saveCoordinator.requestUrgentSave().then((succeeded) => {
            if (!succeeded) {
                ev.preventDefault();
                ev.returnValue = "Unsaved changes";
            }
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

    // enable the archive feature in Actions menu only if the active field is in the view
    get archiveEnabled() {
        return computeArchiveEnabled(this.props.fields, this.model.root.activeFields);
    }

    async shouldExecuteAction(item) {
        const dirty = await this.model.root.isDirty();
        if ((dirty || this.model.root.isNew) && !item.skipSave) {
            const saved = await this.saveCoordinator.requestSave();
            // Block the menu action if the save errored, even if the dialog
            // UX resolved it via "discard": action menus (Duplicate, Archive,
            // etc.) never run after an in-flight save hit a server error.
            return saved !== false && !this.saveCoordinator.lastError;
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

    async deleteRecord() {
        this.deleteRecordsWithConfirmation(this.deleteConfirmationDialogProps, [
            this.model.root,
        ]);
    }

    async beforeExecuteActionButton(clickParams) {
        const record = this.model.root;
        if (clickParams.special !== "cancel") {
            let saved;
            if (clickParams.special === "save" && this.props.saveRecord) {
                // The embedder's saveRecord owns the save itself for
                // special="save" buttons, but the dispatch still goes through
                // the coordinator so ``status`` / ``lastError`` reflect the
                // dialog's Save like every other entry point. With a
                // saveOverride the coordinator injects no onError and
                // rethrows any escaped error (see ``requestSave``), matching
                // the historical direct-call semantics.
                saved = await this.saveCoordinator.requestSave({
                    saveOverride: (r) => this.props.saveRecord(r, clickParams),
                    errorMode: "rethrow",
                });
            } else {
                // Plain save, no dirty pre-check, no error dialog (the caller
                // handles errors via ``useViewButtons``): errors must propagate
                // so ``executeButtonCallback`` can release the UI lock and show
                // a server-error notification. Reload only if we won't close
                // the embedding dialog afterwards.
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
        // TODO: UI should be blocked during pager navigation (disable/enable not done in onPagerUpdate)
        if (canProceed) {
            await executeButtonCallback(
                /** @type {any} */ (this.ui.activeElement),
                () => this.model.load({ resId: false }),
            );
        }
    }

    /**
     * Save the current record. Delegates to `props.saveRecord` if provided,
     * otherwise routes through the save coordinator.
     *
     * Historical note: prior to the FormSaveCoordinator extraction this
     * method assembled its own ``record.save({onError, ...params})`` call
     * with the rethrow-mode error handler.  The coordinator's
     * ``errorMode: "rethrow"`` produces the same observable behavior.
     *
     * @param {Object} [params] - save options (e.g. { reload: false })
     * @returns {Promise<boolean>} whether the save succeeded
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
