// @ts-check
/** @odoo-module native */

/** @module @web/fields/relational/x2many/x2many_field - Full-featured x2many field with embedded list/kanban sub-views and CRUD controls */

import { Component } from "@odoo/owl";
import { Pager } from "@web/components/pager/pager";
import { makeContext } from "@web/core/context";
import { ModelEvent } from "@web/core/events";
import { _t } from "@web/core/l10n/translation";
import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { registerField } from "@web/fields/_registry";
import { standardFieldProps } from "@web/fields/standard_field_props";
import { getFieldDomain } from "@web/model/relational_model/utils";

import { useSelectCreate } from "../many2x_autocomplete.js";
import { useActiveActions } from "../relational_active_actions.js";
import { useAddInlineRecord, useX2ManyCrud } from "../x2many_crud.js";
import { useOpenX2ManyRecord } from "../x2many_dialog.js";

const shared = registry.category("shared_components");
const views = registry.category("views");

export class X2ManyField extends Component {
    static template = "web.X2ManyField";
    static get components() {
        return {
            Pager,
            KanbanRenderer: views.contains("kanban")
                ? views.get("kanban").Renderer
                : undefined,
            ListRenderer: views.contains("list")
                ? views.get("list").Renderer
                : undefined,
            ViewButton: shared.contains("ViewButton")
                ? shared.get("ViewButton")
                : undefined,
        };
    }
    static props = {
        ...standardFieldProps,
        addLabel: { type: String, optional: true },
        editable: { type: String, optional: true },
        viewMode: { type: String, optional: true },
        widget: { type: String, optional: true },
        crudOptions: { type: Object, optional: true },
        string: { type: String, optional: true },
        relatedFields: { type: Object, optional: true },
        views: { type: Object, optional: true },
        domain: { type: [Array, Function], optional: true },
        context: { type: Object },
    };

    /** @type {any} */
    _openRecord;
    /** @type {any} */
    selectCreate;
    /** @type {any} */
    addInLine;
    /** @type {any} */
    activeActions;
    /** @type {import("services").ServiceFactories["action"]} */
    action;
    /** @type {import("services").ServiceFactories["notification"]} */
    notificationService;

    setup() {
        this.field = this.props.record.fields[this.props.name];
        const { linkRecords, saveAndLink, updateRecord, removeRecord } = useX2ManyCrud(
            () => this.list,
            this.isMany2Many,
        );

        this.archInfo = this.props.views?.[this.props.viewMode] || {};
        const classes = this.props.viewMode
            ? ["o_field_x2many", `o_field_x2many_${this.props.viewMode}`]
            : ["o_field_x2many"];
        const computeViewClassName = shared.get("computeViewClassName");
        this.className = computeViewClassName(
            this.props.viewMode,
            this.archInfo.xmlDoc,
            classes,
        );

        const { activeActions, controls } = this.archInfo;
        if (this.props.viewMode === "kanban") {
            this.controls = controls || [];
        }
        const subViewActiveActions = activeActions;
        this.activeActions = useActiveActions({
            crudOptions: {
                ...this.props.crudOptions,
                onDelete: removeRecord,
            },
            fieldType: this.isMany2Many ? "many2many" : "one2many",
            subViewActiveActions,
            getEvalParams: (props) => ({
                evalContext: props.record.evalContext,
                readonly: props.readonly,
                // Re-derived per-props so a post-mount edition-state change
                // (dialog switchMode, readonly<->edit) updates the flag.
                edit: props.record.isInEdition,
            }),
        });

        this.addInLine = useAddInlineRecord({
            // Single params object (not ...args): needed for type-checking
            // against StaticList.addNewRecord's single-argument signature.
            addNew: (params) => this.list.addNewRecord(params),
        });

        const openRecord = useOpenX2ManyRecord(
            /** @type {any} */ ({
                resModel: this.list.resModel,
                activeField: this.activeField,
                activeActions: this.activeActions,
                getList: () => this.list,
                saveRecord: saveAndLink,
                updateRecord,
                isMany2Many: this.isMany2Many,
            }),
        );
        this._openRecord = (params) => {
            const activeElement = document.activeElement;
            openRecord({
                ...params,
                controls: this.controls,
                onClose: () => {
                    // Only restore if the captured node is still in the DOM: the
                    // list can re-render on save, detaching it — focusing a
                    // detached node silently drops focus to <body>.
                    if (activeElement?.isConnected) {
                        /** @type {HTMLElement} */ (activeElement).focus();
                    }
                },
            });
        };
        this.canOpenRecord =
            this.props.viewMode === "list"
                ? !(this.archInfo.editable || this.props.editable)
                : true;

        const selectCreate = useSelectCreate({
            resModel: this.props.record.data[this.props.name].resModel,
            activeActions: this.activeActions,
            isToMany: this.isMany2Many,
            onSelected: (resIds) => linkRecords?.(resIds),
            onCreateEdit: ({ context }) => this._openRecord({ context }),
            onUnselect: this.isMany2Many ? undefined : () => saveAndLink?.(),
        });

        this.selectCreate = (params) => {
            const p = { ...params };
            const currentIds = this.props.record.data[
                this.props.name
            ].currentIds.filter((id) => typeof id === "number");
            p.domain = [...(p.domain || []), "!", ["id", "in", currentIds]];
            return selectCreate(p);
        };
        this.action = useService("action");
        this.notificationService = useService("notification");
    }

    /** @returns {{ fields: Object, views: Object, viewMode: string, string: string }} */
    get activeField() {
        return {
            fields: this.props.relatedFields,
            views: this.props.views,
            viewMode: this.props.viewMode,
            string: this.props.string,
        };
    }

    /** @returns {boolean} */
    get displayControlPanelButtons() {
        return (
            this.props.viewMode === "kanban" && this.canCreate && this.controls.length
        );
    }

    /** @returns {boolean} */
    get canCreate() {
        return (
            ("link" in this.activeActions
                ? this.activeActions.link
                : this.activeActions.create) && !this.props.readonly
        );
    }

    /** @returns {boolean} */
    get isMany2Many() {
        return this.field.type === "many2many" || this.props.widget === "many2many";
    }

    /** @returns {import("@web/model/relational_model/static_list").StaticList} */
    get list() {
        return this.props.record.data[this.props.name];
    }

    /** @returns {{ field: string, model: string, viewMode: string }} */
    get nestedKeyOptionalFieldsData() {
        return {
            field: this.props.name,
            model: this.props.record.resModel,
            viewMode: "form",
        };
    }

    /** @returns {{ offset: number, limit: number, total: number, onUpdate: Function, withAccessKey: boolean }} */
    get pagerProps() {
        const list = this.list;
        return {
            offset: list.offset,
            limit: list.limit,
            total: list.count,
            onUpdate: async ({ offset, limit }) => {
                const initialLimit = this.list.limit;
                const leaved = await list.leaveEditMode();
                if (leaved) {
                    if (
                        initialLimit === limit &&
                        initialLimit === this.list.limit + 1
                    ) {
                        // Unselecting the edited record may have abandoned it. If the page
                        // size was reached before it was created, the limit was temporarily
                        // bumped to keep it on the current page; abandoning it reverts the
                        // limit, so account for that in this offset/limit update.
                        offset -= 1;
                        limit -= 1;
                    }
                    await list.load({ limit, offset });
                    this.render();
                }
            },
            withAccessKey: false,
        };
    }

    /**
     * The kanban renderer, resolved at RENDER time rather than through
     * ``constructor.components``.
     *
     * ``components`` above is a static *getter* so the renderers can be read
     * from the ``views`` registry lazily — the kanban view is not registered
     * yet when this module is evaluated. Subclasses, however, almost always
     * write:
     *
     *     static components = { ...super.components, ListRenderer: MyRenderer };
     *
     * A static *field* replaces the inherited getter with a plain data
     * property, and its initializer runs once at module-load time — while
     * ``views`` still lacks "kanban". That freezes ``KanbanRenderer:
     * undefined`` forever (~40 subclasses do this).
     *
     * Nothing notices on desktop, where an x2many renders through the
     * ``ListRenderer`` branch. On small screens it renders as a kanban, hits
     * the frozen ``undefined`` and throws "Cannot find the definition of
     * component KanbanRenderer", killing the whole form — e.g. the sale order
     * form on mobile, whose lines are a kanban there.
     *
     * An explicit subclass override still wins; the registry is only the
     * fallback for the frozen-undefined case.
     *
     * @returns {typeof import("@odoo/owl").Component | undefined}
     */
    get kanbanRenderer() {
        return (
            this.constructor.components.KanbanRenderer ??
            (views.contains("kanban") ? views.get("kanban").Renderer : undefined)
        );
    }

    /** @returns {Object} Props for the ListRenderer or KanbanRenderer sub-component */
    get rendererProps() {
        const { archInfo } = this;
        const props = {
            archInfo,
            list: this.list,
            openRecord: this.openRecord.bind(this),
            readonly: this.props.readonly || !this.activeActions.write,
        };

        if (this.props.viewMode === "kanban") {
            const recordsDraggable = !this.props.readonly && archInfo.recordsDraggable;
            props.archInfo = { ...archInfo, recordsDraggable };
            props.Compiler = views.get("kanban").Compiler;
            // TODO: apply same logic in the list case
            props.deleteRecord = (record) => {
                if (this.isMany2Many) {
                    return this.list.forget(record);
                }
                return this.list.delete(record);
            };
            if (this.canCreate && !this.controls.length) {
                props.addLabel = this.props.addLabel || _t("Add %s", this.field.string);
                props.onAdd = this.onAdd.bind(this);
            }
            return props;
        }

        const editable =
            (this.archInfo.activeActions.edit && archInfo.editable) ||
            this.props.editable;
        props.activeActions = this.activeActions;
        props.cycleOnTab = false;
        props.editable = !this.props.readonly && editable;
        props.nestedKeyOptionalFieldsData = this.nestedKeyOptionalFieldsData;
        props.onAdd = (params) => {
            params.editable =
                !this.props.readonly &&
                ("editable" in params ? params.editable : editable);
            this.onAdd(params);
        };
        props.onOpenFormView = this.switchToForm.bind(this);
        props.hasOpenFormViewButton = archInfo.editable ? archInfo.openFormView : false;
        return props;
    }

    /**
     * @param {string} invisible - Boolean expression string to evaluate
     * @returns {boolean}
     */
    evalInvisible(invisible) {
        return evaluateBooleanExpr(invisible, this.list.evalContext);
    }

    /**
     * @param {Object} record - The x2many record to open in form view
     * @param {{ newWindow?: boolean }} options
     */
    async switchToForm(record, options) {
        let resId;
        if (record.isNew) {
            // New records have no resId until saved. Snapshot the create-order
            // reconciliation data BEFORE the save clears the CREATE commands,
            // then ask the model (which owns the command log) to map the
            // virtualId back to the assigned resId.
            const reconciliation = this.list.snapshotCreateReconciliation();
            const saved = await this.props.record.save();
            if (!saved) {
                return;
            }
            // Fast path: if the save reconciled this record object in place
            // (its resId is now populated), trust it directly.
            if (record.resId) {
                resId = record.resId;
            } else {
                resId = this.list.resolveCreatedResId(reconciliation, record);
                if (resId === undefined) {
                    // Ambiguous mapping (row count mismatch): ask the user to
                    // save rather than opening the wrong record.
                    return this.notificationService.add(
                        _t("Please save your changes first"),
                        {
                            type: "danger",
                        },
                    );
                }
            }
        } else {
            const saved = await this.props.record.save();
            if (!saved) {
                return;
            }
            resId = record.resId;
        }

        this.action.doAction(
            {
                type: "ir.actions.act_window",
                views: [[false, "form"]],
                res_id: resId,
                res_model: this.list.resModel,
                context: this.getFormActionContext(),
            },
            {
                props: { resIds: this.list.resIds },
                newWindow: options.newWindow,
            },
        );
    }

    /** @returns {Object} Context passed to the form action when switching views */
    getFormActionContext() {
        return this.props.context;
    }

    /** @param {{ context?: Object, editable?: string }} [params] */
    async onAdd({ context, editable } = /** @type {any} */ ({})) {
        context = makeContext([this.props.context, context]);
        if (this.isMany2Many) {
            const domain = getFieldDomain(
                this.props.record,
                this.props.name,
                this.props.domain,
            );
            const { string } = this.props;
            const title = _t("Add: %s", string);
            return this.selectCreate({ domain, context, title });
        }
        if (editable) {
            const editedRecord = this.list.editedRecord;
            if (editedRecord) {
                const proms = [];
                this.list.model.bus.trigger(ModelEvent.NEED_LOCAL_CHANGES, { proms });
                // Flush in-flight input-field commits collected via
                // NEED_LOCAL_CHANGES before leaving edit mode. (A former
                // ``editedRecord._updatePromise`` entry here was dead — that
                // property exists nowhere, so ``Promise.all`` awaited
                // ``undefined``; ordering for non-input updates is guaranteed by
                // ``leaveEditMode`` re-taking ``model.mutex``.)
                await Promise.all(proms);
                await this.list.leaveEditMode({ canAbandon: false });
            }
            if (!this.list.editedRecord) {
                return this.addInLine({ context, editable });
            }
            return;
        }
        return this._openRecord({ context });
    }

    async openRecord(record) {
        if (this.canOpenRecord) {
            return this._openRecord({
                record,
                context: this.props.context,
                readonly: this.props.readonly,
            });
        }
    }
}

export const x2ManyField = {
    component: X2ManyField,
    displayName: _t("Relational table"),
    supportedTypes: ["one2many", "many2many"],
    useSubView: true,
    extractProps: (
        { attrs, relatedFields, viewMode, views, widget, options, string },
        dynamicInfo,
    ) => {
        const props = {
            addLabel: attrs["add-label"],
            context: dynamicInfo.context,
            domain: dynamicInfo.domain,
            crudOptions: options,
            string,
        };
        if (viewMode) {
            props.views = views;
            props.viewMode = viewMode;
            props.relatedFields = relatedFields;
        }
        if (widget) {
            props.widget = widget;
        }
        return props;
    },
};

registerField({ name: "one2many", aliases: ["many2many"] }, x2ManyField);
