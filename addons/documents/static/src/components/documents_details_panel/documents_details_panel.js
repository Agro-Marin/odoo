/** @odoo-module native */
import { _t } from "@web/core/translation";
import { ModelSelector } from "@web/components/model_selector/model_selector";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { formatFloat } from "@web/core/utils/format/numbers";
import { CharField } from "@web/fields/basic/char/char_field";
import { Many2OneAvatarField } from "@web/fields/relational/many2one_avatar/many2one_avatar_field";
import { Many2OneField } from "@web/fields/relational/many2one";
import { SelectCreateDialog } from "@web/views/view_dialogs";

import { DocumentsDetailsMany2ManyTagsField } from "@documents/views/fields/documents_details_many2many_tags/documents_details_many2many_tags_field";
import { DocumentsDetailsMany2OneField } from "@documents/views/fields/documents_details_many2one/documents_details_many2one_field";
import { DocumentsTypeIcon } from "@documents/views/fields/documents_type_icon/documents_type_icon";

import { Component, onWillRender, onWillUpdateProps, reactive, useState } from "@odoo/owl";

export class DocumentsDetailsPanel extends Component {
    static components = {
        CharField,
        DocumentsDetailsMany2ManyTagsField,
        DocumentsDetailsMany2OneField,
        DocumentsTypeIcon,
        Many2OneAvatarField,
        Many2OneField,
        ModelSelector,
    };
    static props = {
        // Not optional: `setup` reads `props.record.data` straight away, and the
        // only instantiation site (documents.DocumentsViews.RightPanel) already
        // refuses to mount this component unless `focusedRecord` is a real
        // record -- see its `panelDisabled` getter. Declaring it optional only
        // stopped OWL's dev-mode validation from catching a violation of the
        // contract the code actually relies on.
        record: { type: Object },
        nbViewItems: { type: Number, optional: true },
    };
    static template = "documents.DocumentsDetailsPanel";

    setup() {
        this.action = useService("action");
        /** @type {import("@documents/core/document_service").DocumentService} */
        this.documentService = useService("document.document");
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        // Rebuilt on every render, deliberately: the wrapper below is a plain
        // `Proxy` over a callback-less `reactive()`, so nothing subscribes the
        // field components to the record. What re-renders them is precisely this
        // fresh `Proxy` identity arriving as a changed `record` prop. Building it
        // once per record (or binding the reactive to `this.render`) stops tag
        // edits from ever showing -- see the "rendering for editors" test.
        onWillRender(() => {
            this.record = wrapAsDetailsPanelRecord(this.props.record);
        });

        // Use a state for the model to not write on the record the model without record id
        this.state = useState({
            resModel: this.props.record.data.res_model,
            resModelName: this.props.record.data.res_model_name || "",
            models: [],
        });
        this.documentService
            .getDetailsPanelResModels()
            .then((models) => (this.state.models = models));
        onWillUpdateProps((nextProps) => {
            this.state.resModel = nextProps.record.data.res_model;
            this.state.resModelName = nextProps.record.data.res_model_name || "";
        });
    }

    async openLinkedRecord() {
        const { res_model, res_id } = this.record.data || {};
        if (!res_id?.resId || !res_model) {
            return;
        }
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_id: res_id.resId,
            res_model,
            views: [[false, "form"]],
            target: "current",
        });
    }

    /**
     * Open this document's access history.
     *
     * The action is built server-side so the domain and the grouping live with
     * the model rather than being restated here.
     */
    async openAccessLog() {
        const action = await this.orm.call(
            "documents.document",
            "action_view_access_log",
            [this.record.resId],
        );
        return this.action.doAction(action);
    }

    /**
     * Whether to offer the access log at all.
     *
     * `documents.access.log` is readable by managers only, so showing this to
     * anyone else would offer a button that answers with an access error.
     */
    get canViewAccessLog() {
        return this.documentService.userIsDocumentManager && !!this.record.resId;
    }

    get userPermissionViewOnly() {
        return (
            !!this.record.data?.lock_uid ||
            this.record.data?.user_permission !== "edit" ||
            (!this.documentService.userIsDocumentManager &&
                this.record.data?.user_folder_id === "COMPANY")
        );
    }

    get fileSize() {
        const data = this.record.data;
        const isFolderTotal = this.props.record.isContainer;
        if (data.type === "folder" && !isFolderTotal) {
            return "";
        }
        const nBytes = data.file_size || 0;
        if (!nBytes) {
            return "";
        }
        return `${isFolderTotal ? "~" : ""}${formatFloat(nBytes, { humanReadable: true })}B`;
    }

    get rootFolderPlaceholder() {
        return {
            MY: _t("My Drive"),
            COMPANY: _t("Company"),
            SHARED: _t("Shared with me"),
        }[this.props.record.data?.user_folder_id];
    }

    get activeCompanies() {
        return user.activeCompanies.map((c) => c.id);
    }

    async onModelSelected(value) {
        this.state.resModel = value.technical;
        this.state.resModelName = value.label || "";
        await this.record.update({ res_id: false, res_model: false }, { save: true });
        if (this.state.resModel) {
            this.dialog.add(
                SelectCreateDialog,
                {
                    title: _t("Select a Record To Link"),
                    noCreate: true,
                    multiSelect: false,
                    resModel: this.state.resModel,
                    onSelected: async (resIds) => {
                        if (resIds.length) {
                            await this.onResIdUpdate(resIds);
                        }
                    },
                },
                {
                    onClose: () => {
                        if (!this.record.data.res_id) {
                            this.onRecordReset();
                        }
                    },
                }
            );
        }
    }

    async onRecordReset() {
        await this.onModelSelected({ technical: false, label: false });
    }

    async onResIdUpdate(value) {
        if (this.state.resModel) {
            await this.record.update(
                { res_id: value[0], res_model: this.state.resModel },
                { save: true }
            );
        }
    }
}

/**
 * Answer `isDetailsPanelRecord = true` so `DocumentsRecordMixin.update` saves the
 * edit and leaves the rest of the selection alone -- a focused record is not
 * necessarily selected, and editing it here must not multi-edit.
 *
 * It has to be a wrapper rather than an `update(changes, options)` flag: the panel
 * does not call `update` itself, the field components it renders do, and they
 * pass options of their own.
 *
 * @param {Object} record
 * @returns {Object}
 */
function wrapAsDetailsPanelRecord(record) {
    return new Proxy(reactive(record), {
        get(target, prop, receiver) {
            return prop === "isDetailsPanelRecord" || Reflect.get(target, prop, receiver);
        },
    });
}
