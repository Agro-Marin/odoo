// @ts-check
/** @odoo-module native */

/** @module @web/fields/relational/many2many_binary/many2many_binary_field */

import { Component } from "@odoo/owl";
import { FileInput } from "@web/components/file_input/file_input";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { registerField } from "@web/fields/_registry";
import { fieldHandle } from "@web/fields/field_handle";
import { standardFieldProps } from "@web/fields/standard_field_props";

import { useX2ManyCrud } from "../x2many_crud.js";

export class Many2ManyBinaryField extends Component {
    static template = "web.Many2ManyBinaryField";
    static components = {
        FileInput,
    };
    static props = {
        ...standardFieldProps,
        acceptedFileExtensions: { type: String, optional: true },
        className: { type: String, optional: true },
        numberOfFiles: { type: Number, optional: true },
    };

    /** @returns {import("@web/fields/field_handle").FieldHandle} */
    get field() {
        return fieldHandle(this);
    }

    /** @type {import("services").ServiceFactories["notification"]} */
    notification;
    /** @type {ReturnType<typeof useX2ManyCrud>} */
    operations;

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.operations = useX2ManyCrud(() => this.field.value, true);
    }

    /** @returns {string} */
    get uploadText() {
        return this.field.definition.string;
    }
    /** @returns {Array<Object>} */
    get files() {
        return this.field.value.records.map((/** @type {any} */ record) => ({
            ...record.data,
            id: record.resId,
        }));
    }

    /**
     * @param {number} id
     * @returns {string}
     */
    getUrl(id) {
        return `/web/content/${id}?download=true`;
    }

    /**
     * @param {{ name: string }} file
     * @returns {string}
     */
    getDownloadTooltip(file) {
        return _t("Download %s", file.name);
    }

    /**
     * @param {{ name: string }} file
     * @returns {string}
     */
    getExtension(file) {
        return file.name.replace(/^.*\./, "");
    }

    /**
     * @param {{ mimetype: string }} file
     * @returns {boolean}
     */
    isImage(file) {
        return file.mimetype.startsWith("image/");
    }

    /** @param {Array<{ id: number, error?: string }>} files */
    async onFileUploaded(files) {
        const uploadedIds = [];
        for (const file of files) {
            if (file.error) {
                this.notification.add(file.error, {
                    title: _t("Uploading error"),
                    type: "danger",
                });
                continue;
            }
            uploadedIds.push(file.id);
        }
        if (uploadedIds.length) {
            await this.operations.linkRecords(uploadedIds);
        }
    }

    /** @param {number} deleteId */
    async onFileRemove(deleteId) {
        const record = this.field.value.records.find(
            (/** @type {any} */ record) => record.resId === deleteId,
        );
        if (!record) {
            return;
        }
        return this.operations.removeRecord(record);
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const many2ManyBinaryField = {
    component: Many2ManyBinaryField,
    supportedOptions: [
        {
            label: _t("Accepted file extensions"),
            name: "accepted_file_extensions",
            type: "string",
        },
        {
            label: _t("Number of files"),
            name: "number_of_files",
            type: "integer",
        },
    ],
    supportedTypes: ["many2many"],
    isEmpty: () => false,
    relatedFields: [
        { name: "name", type: "char" },
        { name: "mimetype", type: "char" },
    ],
    extractProps: ({ attrs, options }) => ({
        acceptedFileExtensions: options.accepted_file_extensions,
        className: attrs.class,
        numberOfFiles: options.number_of_files,
    }),
};

registerField("many2many_binary", many2ManyBinaryField);
