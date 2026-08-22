// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";
import { TagsList } from "@web/components/tags_list/tags_list";
import { _t } from "@web/core/translation";
import { useAutofocus } from "@web/core/utils/hooks";
import { Operation } from "@web/core/utils/operation";
import { Field, fieldVisualFeedback } from "@web/fields/field";
import { Dialog } from "@web/ui/dialog/dialog";

export class ListConfirmationDialog extends Component {
    static template = "web.ListView.ConfirmationModal";
    static components = { Dialog, Field, TagsList };
    static props = {
        close: Function,
        title: {
            validate: (/** @type {any} */ m) =>
                typeof m === "string" ||
                (typeof m === "object" && typeof m.toString === "function"),
            optional: true,
        },
        confirm: { type: Function, optional: true },
        cancel: { type: Function, optional: true },
        isDomainSelected: Boolean,
        fields: Object,
        nbRecords: Number,
        nbValidRecords: Number,
        record: Object,
        changes: Object,
    };
    static defaultProps = {
        title: _t("Confirmation"),
    };

    setup() {
        useAutofocus();
    }

    /** @returns {string} */
    get validRecordsText() {
        return _t(
            "Among the %(total)s selected records, %(valid_count)s are valid for this update.",
            {
                total: this.props.nbRecords,
                valid_count: this.props.nbValidRecords,
            },
        );
    }

    /** @returns {string} */
    get updateConfirmationText() {
        return _t("Are you sure you want to update %(count)s records?", {
            count: this.props.nbValidRecords,
        });
    }

    /** @returns {boolean} */
    get showTip() {
        return this.props.fields.some((/** @type {any} */ field) =>
            ["monetary", "integer", "float"].includes(field.fieldNode?.type),
        );
    }

    _cancel() {
        if (this.props.cancel) {
            this.props.cancel();
        }
        this.props.close();
    }

    async _confirm() {
        if (this.props.confirm) {
            await this.props.confirm();
        }
        this.props.close();
    }

    /**
     * @param {any[]} records
     * @param {{ fieldNode: any }} field
     * @returns {{ id: any, resId: any, text: string, colorIndex: any }[]}
     */
    getTagProps(records, field) {
        const colorField = field.fieldNode.options?.color_field;
        return records.map((record) => ({
            id: record.id,
            resId: record.resId,
            text: record.data.display_name,
            colorIndex: colorField ? record.data[colorField] : undefined,
        }));
    }

    /**
     * @param {{ fieldNode: any, name: string }} field
     * @returns {boolean}
     */
    isValueEmpty(field) {
        const fieldNode = field.fieldNode || {};
        return fieldVisualFeedback(
            fieldNode.field || {},
            this.props.record,
            field.name,
            {
                ...fieldNode,
                readonly: true,
            },
        ).empty;
    }

    /**
     * @param {{ name: string }} field
     * @returns {boolean}
     */
    isValueOperation(field) {
        return this.props.changes[field.name] instanceof Operation;
    }
}
