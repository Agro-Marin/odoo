// @ts-check
/** @odoo-module native */

/** @module @web/fields/relational/x2many_dialog */

import { Component, useComponent, useEffect, useEnv, useSubEnv } from "@odoo/owl";
import { useAction } from "@web/core/action_port";
import { makeContext } from "@web/core/context";
import { ModelEvent } from "@web/core/events";
import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { registry } from "@web/core/registry";
import { sharedComponents as shared } from "@web/core/shared_components";
import { _t } from "@web/core/translation";
import { createElement, parseXML } from "@web/core/utils/dom/xml";
import {
    useBus,
    useChildRef,
    useOwnedDialogs,
    useService,
} from "@web/core/utils/hooks";
import { extractFieldsFromArchInfo } from "@web/model/relational_model/utils";
import { Dialog } from "@web/ui/dialog/dialog";

const views = registry.category("views");
export class X2ManyFieldDialog extends Component {
    static template = "web.X2ManyFieldDialog";
    static get components() {
        return {
            Dialog,
            FormRenderer: views.get("form").Renderer,
            ViewButton: shared.get("ViewButton"),
        };
    }
    static props = {
        archInfo: Object,
        close: Function,
        record: Object,
        addNew: Function,
        save: Function,
        title: String,
        newRecordTitle: { type: String, optional: true },
        delete: { optional: true },
        deleteButtonLabel: { optional: true },
        config: Object,
        controls: { type: Array, optional: true },
    };
    static defaultProps = {
        controls: [],
    };
    /** @type {import("@web/core/action_port").ActionPort} */
    actionService;

    setup() {
        this.actionService = useAction();
        this.archInfo = this.props.archInfo;
        this.record = this.props.record;
        this.title = this.props.title;
        this.contentClass = shared.get("computeViewClassName")(
            "form",
            this.archInfo.xmlDoc,
        );
        useSubEnv({ config: this.props.config });
        this.env.dialogData.dismiss = () => this.discard();

        // Not forced. This is the per-dialog form of the blanket that used to
        // live in `useModelWithSampleData`: the dialog re-renders on a model
        // update, but its children re-render off their own subscriptions
        // rather than being swept along unconditionally.
        useBus(this.record.model.bus, ModelEvent.UPDATE, () => this.render());

        this.modalRef = useChildRef();

        const reload = () => this.record.load();

        shared.get("useViewButtons")(/** @type {any} */ (this.modalRef), {
            reload,
            beforeExecuteAction: this.beforeExecuteActionButton.bind(this),
        });

        this._computePermissions();

        if (this.archInfo.xmlDoc.querySelector("footer:not(field footer)")) {
            this.archInfo = {
                ...this.archInfo,
                xmlDoc: this.archInfo.xmlDoc.cloneNode(true),
            };
            this.footerArchInfo = { ...this.archInfo };
            this.footerArchInfo.xmlDoc = createElement("t");
            this.footerArchInfo.xmlDoc.append(
                ...this.archInfo.xmlDoc.querySelectorAll("footer:not(field footer)"),
            );
            this.footerArchInfo.arch = this.footerArchInfo.xmlDoc.outerHTML;
            this.archInfo.arch = this.archInfo.xmlDoc.outerHTML;
        }

        const { autofocusFieldIds, disableAutofocus } = this.archInfo;
        if (!disableAutofocus) {
            useEffect(
                (isInEdition) => {
                    let elementToFocus;
                    if (isInEdition) {
                        for (const id of autofocusFieldIds) {
                            elementToFocus = /** @type {any} */ (
                                this.modalRef
                            ).el.querySelector(`#${id}`);
                            if (elementToFocus) {
                                break;
                            }
                        }
                        elementToFocus =
                            elementToFocus ||
                            /** @type {any} */ (this.modalRef).el.querySelector(
                                ".o_field_widget input",
                            );
                    } else {
                        elementToFocus = /** @type {any} */ (
                            this.modalRef
                        ).el.querySelector("button.btn-primary");
                    }
                    if (elementToFocus) {
                        elementToFocus.focus();
                    } else {
                        /** @type {any} */ (this.modalRef).el.focus();
                    }
                },
                () => [this.record.isInEdition],
            );
        }
        shared.get("useFormViewInDialog")();
    }

    _computePermissions() {
        this.readonly = Boolean(this.record.resId && !this.archInfo.activeActions.edit);
        this.canCreate = !this.record.resId;
    }

    /** @returns {Object} */
    get dialogProps() {
        const props = {
            title: this.title,
            withBodyPadding: false,
            modalRef: this.modalRef,
            contentClass: this.contentClass,
        };
        if (!this.record.isNew) {
            props.onExpand = async () => {
                await this.save({ saveAndNew: false });
                this.actionService.doAction({
                    type: "ir.actions.act_window",
                    res_model: this.props.record.resModel,
                    res_id: this.props.record.resId,
                    views: [[false, "form"]],
                });
            };
        }
        return props;
    }

    /** @returns {boolean} */
    get displayDeleteButton() {
        const deleteControl = this.props.controls.find(
            (control) => control.type === "delete",
        );
        return (
            !deleteControl ||
            !evaluateBooleanExpr(deleteControl.invisible, this.record.evalContext)
        );
    }

    /** @param {{ special?: string }} clickParams */
    async beforeExecuteActionButton(clickParams) {
        if (clickParams.special !== "cancel") {
            return this.record.save();
        }
    }

    async discard() {
        if (this.record.isInEdition) {
            await this.record.discard();
        }
        this.props.close();
    }

    /**
     * @param {{ saveAndNew: boolean }} params
     * @returns {Promise<boolean>}
     */
    save({ saveAndNew }) {
        return shared.get("executeButtonCallback")(
            /** @type {any} */ (this.modalRef).el,
            async () => {
                if (
                    await this.record.checkValidity({
                        displayNotification: true,
                    })
                ) {
                    await this.props.save(this.record);
                    if (saveAndNew) {
                        await this.record.switchMode("readonly");
                        this.record = await this.props.addNew();
                        this._computePermissions();
                    }
                } else {
                    return false;
                }
                if (!saveAndNew) {
                    this.props.close();
                }
                return true;
            },
        );
    }

    async remove() {
        await this.props.delete();
        this.props.close();
    }

    async saveAndNew() {
        const saved = await this.save({ saveAndNew: true });
        if (saved) {
            this.title = this.props.newRecordTitle || this.title;
            this.render(true);
        }
    }
}

/**
 * @param {Object} params
 * @param {Object} params.list
 * @param {Object} params.context
 * @param {Object} params.activeField
 * @param {Object} params.viewService
 * @param {Object} params.env
 * @returns {Promise<{archInfo: Object, fields: Object}>}
 */
async function getFormViewInfo({ list, context, activeField, viewService, env }) {
    let formArchInfo = activeField.views.form;
    let fields = activeField.fields;
    const comodel = list.resModel;
    if (!formArchInfo) {
        const {
            fields: formFields,
            relatedModels,
            views: loadedViews,
        } = await viewService.loadViews({
            context: makeContext([list.context, context]),
            resModel: comodel,
            views: [[false, "form"]],
        });
        const { ArchParser } = views.get("form");
        const xmlDoc = parseXML(loadedViews.form.arch);
        formArchInfo = new ArchParser().parse(xmlDoc, relatedModels, comodel);
        fields = { ...list.fields, ...formFields };
    }

    await shared.get("loadSubViews")(
        formArchInfo.fieldNodes,
        fields,
        {},
        comodel,
        viewService,
        env.isSmall,
    );

    return { archInfo: formArchInfo, fields };
}

/**
 * @param {Object} params
 * @param {Object} params.activeField
 * @param {Object} params.activeActions
 * @param {Function} params.getList
 * @param {Function} params.updateRecord
 * @param {Function} params.saveRecord
 * @param {boolean} params.isMany2Many
 * @returns {Function}
 */
export function useOpenX2ManyRecord({
    activeField,
    activeActions,
    getList,
    updateRecord,
    saveRecord,
    isMany2Many,
}) {
    const viewService = useService("view");
    const env = useEnv();
    const component = useComponent();

    const addDialog = useOwnedDialogs();
    const viewMode = activeField.viewMode;

    async function openRecord({ record, readonly, context, title, controls, onClose }) {
        let newRecordTitle;
        if (!title) {
            title = record
                ? _t("Open: %s", activeField.string)
                : _t("Create %s", activeField.string);
            newRecordTitle = _t("New: %s", activeField.string);
        }
        const list = getList();
        let { archInfo, fields: _fields } = await getFormViewInfo({
            list,
            context,
            activeField,
            viewService,
            env,
        });
        if (!component.props.record.isInEdition) {
            archInfo = {
                ...archInfo,
                activeActions: { ...archInfo.activeActions, edit: false },
            };
        }

        const { activeFields, fields } = extractFieldsFromArchInfo(archInfo, _fields);

        let deleteRecord;
        let deleteButtonLabel = undefined;
        const isDuplicate = !!record;

        const params = { activeFields, fields };
        if (isMany2Many) {
            params.mode = activeActions.write ? "edit" : "readonly";
        } else {
            params.mode = readonly || !activeActions.write ? "readonly" : "edit";
        }
        const creationParams = {
            ...params,
            context: makeContext([list.context, context]),
            withoutParent: isMany2Many,
        };
        if (record) {
            const { delete: canDelete, onDelete } = activeActions;
            deleteRecord =
                viewMode === "kanban" && canDelete ? () => onDelete(record) : null;
            deleteButtonLabel =
                activeActions.type === "one2many" ? _t("Delete") : _t("Remove");
        }
        record = await list.extendRecord(record ? params : creationParams, record);

        const _onClose = () => {
            list.editedRecord?.switchMode("readonly");
            onClose?.();
        };

        addDialog(
            X2ManyFieldDialog,
            {
                config: env.config,
                archInfo,
                record,
                controls,
                addNew: () => getList().extendRecord(creationParams),
                save: (rec) => {
                    if (isDuplicate && rec.id === record.id) {
                        return updateRecord(rec);
                    } else {
                        return saveRecord(rec);
                    }
                },
                title,
                newRecordTitle,
                delete: deleteRecord,
                deleteButtonLabel: deleteButtonLabel,
            },
            { onClose: _onClose },
        );
    }

    let recordIsOpen = false;
    return async (params) => {
        if (recordIsOpen) {
            return;
        }
        recordIsOpen = true;

        const onClose = params.onClose;
        params = {
            ...params,
            onClose: (...args) => {
                recordIsOpen = false;
                if (onClose) {
                    return onClose(...args);
                }
            },
        };

        try {
            return await openRecord(params);
        } catch (e) {
            recordIsOpen = false;
            throw e;
        }
    };
}
