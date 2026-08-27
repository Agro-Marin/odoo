// @ts-check
/** @odoo-module native */

import { Pager } from "@web/components/pager/pager";
import { useAction } from "@web/core/action_port";
import { makeContext } from "@web/core/context";
import { ModelEvent } from "@web/core/events";
import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { registry } from "@web/core/registry";
import { sharedComponents as shared } from "@web/core/shared_components";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { registerField } from "@web/fields/_registry";
import { FieldComponent } from "@web/fields/field_component";
import { archAttribute } from "@web/fields/field_options";
import { standardFieldProps } from "@web/fields/standard_field_props";
import { getFieldDomain } from "@web/model/relational_model";

import { useSelectCreate } from "../many2x_autocomplete.js";
import { useActiveActions } from "../relational_active_actions.js";
import { useAddInlineRecord, useX2ManyCrud } from "../x2many_crud.js";
import { useOpenX2ManyRecord } from "../x2many_dialog.js";

const views = registry.category("views");

export class X2ManyField extends FieldComponent {
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
    /** @type {import("@web/core/action_port").ActionPort} */
    action;
    /** @type {import("services").ServiceFactories["notification"]} */
    notificationService;

    setup() {
        this.fieldDefinition = this.field.definition;
        const crud = useX2ManyCrud(() => this.list, this.isMany2Many);

        this.setupSubView();
        this.activeActions = useActiveActions({
            crudOptions: (props) => ({
                ...props.crudOptions,
                onDelete: crud.removeRecord,
            }),
            fieldType: this.isMany2Many ? "many2many" : "one2many",
            subViewActiveActions: this.archInfo.activeActions,
            getEvalParams: (props) => ({
                evalContext: props.record.evalContext,
                readonly: props.readonly,
                edit: props.record.isInEdition,
            }),
        });
        this.addInLine = useAddInlineRecord({
            addNew: (params) => this.list.addNewRecord(params),
        });
        this.setupRecordOpeners(crud);

        this.action = useAction();
        this.notificationService = useService("notification");
    }

    setupSubView() {
        this.archInfo = this.props.viewMode
            ? this.props.views[this.props.viewMode]
            : {};
        const classes = this.props.viewMode
            ? ["o_field_x2many", `o_field_x2many_${this.props.viewMode}`]
            : ["o_field_x2many"];
        this.className = shared.get("computeViewClassName")(
            this.props.viewMode,
            this.archInfo.xmlDoc,
            classes,
        );
        if (this.props.viewMode === "kanban") {
            this.controls = this.archInfo.controls || [];
        }
    }

    /**
     * @param {{ linkRecords: Function, saveAndLink: Function, updateRecord: Function }} crud
     */
    setupRecordOpeners({ linkRecords, saveAndLink, updateRecord }) {
        const openRecord = useOpenX2ManyRecord({
            activeField: this.activeField,
            activeActions: this.activeActions,
            getList: () => this.list,
            saveRecord: saveAndLink,
            updateRecord,
            isMany2Many: this.isMany2Many,
        });
        this._openRecord = (params) => {
            const activeElement = document.activeElement;
            openRecord({
                ...params,
                controls: this.controls,
                onClose: () => {
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
            resModel: this.list.resModel,
            activeActions: this.activeActions,
            isToMany: this.isMany2Many,
            onSelected: (resIds) => linkRecords?.(resIds),
            onCreateEdit: ({ context }) => this._openRecord({ context }),
            onUnselect: this.isMany2Many ? undefined : () => saveAndLink?.(),
        });
        this.selectCreate = (params) => {
            const p = { ...params };
            const currentIds = this.list.currentIds.filter(
                (id) => typeof id === "number",
            );
            p.domain = [...(p.domain || []), "!", ["id", "in", currentIds]];
            return selectCreate(p);
        };
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
        return Boolean(
            this.props.viewMode === "kanban" && this.canCreate && this.controls.length,
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
        return (
            this.fieldDefinition.type === "many2many" ||
            this.props.widget === "many2many"
        );
    }

    /** @returns {import("@web/model/relational_model/static_list").StaticList} */
    get list() {
        return this.field.value;
    }

    /** @returns {{ field: string, model: string, viewMode: string }} */
    get nestedKeyOptionalFieldsData() {
        return {
            field: this.props.name,
            model: this.props.record.resModel,
            viewMode: "form",
        };
    }

    /**
     * @returns {{ offset: number, limit: number, total: number, onUpdate: Function, withAccessKey: boolean }}
     */
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
     * @returns {typeof import("@odoo/owl").Component | undefined}
     */
    get kanbanRenderer() {
        const ctor = /** @type {typeof X2ManyField} */ (this.constructor);
        return (
            ctor.components.KanbanRenderer ??
            (views.contains("kanban") ? views.get("kanban").Renderer : undefined)
        );
    }

    /** @returns {Object} */
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
            props.deleteRecord = (record) => {
                if (this.isMany2Many) {
                    return this.list.forget(record);
                }
                return this.list.delete(record);
            };
            if (this.canCreate && !this.controls.length) {
                props.addLabel =
                    this.props.addLabel || _t("Add %s", this.fieldDefinition.string);
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
     * @param {string} invisible
     * @returns {boolean}
     */
    evalInvisible(invisible) {
        return evaluateBooleanExpr(invisible, this.list.evalContext);
    }

    /**
     * @param {Object} record
     * @param {{ newWindow?: boolean }} options
     */
    async switchToForm(record, options) {
        let resId;
        if (record.isNew) {
            const reconciliation = this.list.snapshotCreateReconciliation();
            const saved = await this.props.record.save();
            if (!saved) {
                return;
            }
            if (record.resId) {
                resId = record.resId;
            } else {
                resId = this.list.resolveCreatedResId(reconciliation, record);
                if (resId === undefined) {
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

    /** @returns {Object} */
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
    supportedAttributes: [
        archAttribute("add-label", _t("Add button label"), {
            help: _t('Text of the row/card creation button, replacing "Add a line".'),
        }),
    ],
    supportedOptions: [
        {
            label: _t("Can create"),
            name: "create",
            type: "string",
            help: _t(
                "Python domain; creation is offered only for records it matches. `False` forbids it outright.",
            ),
        },
        {
            label: _t("Can delete"),
            name: "delete",
            type: "string",
            help: _t("Python domain gating the per-row delete action."),
        },
        {
            label: _t("Can link"),
            name: "link",
            type: "string",
            help: _t("many2many only: Python domain gating 'Add' / the select dialog."),
        },
        {
            label: _t("Can unlink"),
            name: "unlink",
            type: "string",
            help: _t(
                "many2many only: Python domain gating removal of an existing link.",
            ),
        },
        {
            label: _t("Can write"),
            name: "write",
            type: "string",
            help: _t(
                "Python domain; when it does not match, the sub-view is read-only.",
            ),
        },
    ],
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
            // Named, not `options` wholesale: these five are the entire
            // vocabulary `useActiveActions` reads, and spelling them out is
            // what lets `supportedOptions` above be checked against the code
            // in both directions. `createEdit` and `edit` were reachable the
            // old way and are not declared here -- no arch in any repo sets
            // either, and `edit` was overridden unconditionally by
            // `getEvalParams` anyway.
            crudOptions: {
                create: options.create,
                delete: options.delete,
                link: options.link,
                unlink: options.unlink,
                write: options.write,
            },
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
