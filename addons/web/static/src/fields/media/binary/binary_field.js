// @ts-check
/** @odoo-module native */

/** @module @web/fields/media/binary/binary_field */

import { Component } from "@odoo/owl";
import { FileUploader } from "@web/core/file_upload/file_handler";
import { download } from "@web/core/network/download";
import { _t } from "@web/core/translation";
import { isBinarySize, toBase64Length } from "@web/core/utils/format/binary";
import { useService } from "@web/core/utils/hooks";
import { registerField } from "@web/fields/_registry";
import { standardFieldProps } from "@web/fields/standard_field_props";

export const MAX_FILENAME_SIZE_BYTES = 0xff;

const textEncoder = new TextEncoder();

/**
 * @param {string} str
 * @param {number} maxBytes
 * @returns {string}
 */
function truncateToByteLength(str, maxBytes) {
    if (textEncoder.encode(str).length <= maxBytes) {
        return str;
    }
    let bytes = 0;
    let end = 0;
    for (const char of str) {
        const charBytes = textEncoder.encode(char).length;
        if (bytes + charBytes > maxBytes) {
            break;
        }
        bytes += charBytes;
        end += char.length;
    }
    return str.slice(0, end);
}

export class BinaryField extends Component {
    static template = "web.BinaryField";
    static components = {
        FileUploader,
    };
    static props = {
        ...standardFieldProps,
        acceptedFileExtensions: { type: String, optional: true },
        allowedMIMETypes: { type: String, optional: true },
        fileNameField: { type: String, optional: true },
    };
    static defaultProps = {
        acceptedFileExtensions: "*",
    };

    setup() {
        this.notification = useService("notification");
    }

    /** @returns {string} */
    get fileName() {
        const fileName = this.props.record.data[this.props.fileNameField];
        if (fileName) {
            return truncateToByteLength(fileName, MAX_FILENAME_SIZE_BYTES);
        }
        let value = this.props.record.data[this.props.name];
        value = value && typeof value === "string" ? value : "";
        return value.slice(0, toBase64Length(MAX_FILENAME_SIZE_BYTES));
    }

    /**
     * @param {{ data: string|false, name: string }} payload
     * @returns {Promise<any>}
     */
    update({ data, name }) {
        const { fileNameField, record } = this.props;
        const changes = { [this.props.name]: data || false };
        if (fileNameField in record.fields && record.data[fileNameField] !== name) {
            changes[fileNameField] = name || "";
        }
        return this.props.record.update(changes);
    }

    /** @returns {{ model: string, field: string, id: number } & Record<string, any>} */
    getDownloadData() {
        return {
            model: this.props.record.resModel,
            id: this.props.record.resId,
            field: this.props.name,
            filename_field: this.props.fileNameField,
            filename: this.fileName || "",
            download: true,
            data: isBinarySize(this.props.record.data[this.props.name])
                ? null
                : this.props.record.data[this.props.name],
        };
    }

    async onFileDownload() {
        await download({
            data: this.getDownloadData(),
            url: "/web/content",
        });
    }
}

export class ListBinaryField extends BinaryField {
    static template = "web.ListBinaryField";
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const binaryField = {
    component: BinaryField,
    displayName: _t("File"),
    supportedOptions: [
        {
            label: _t("Accepted file extensions"),
            name: "accepted_file_extensions",
            type: "string",
        },
        {
            label: _t("Allowed file mimetype"),
            name: "allowed_mime_type",
            type: "string",
        },
    ],
    supportedTypes: ["binary"],
    // Read to label and name the download, and written on upload, so it has to
    // be loaded even when the view does not render it -- otherwise `fileName`
    // falls through to slicing the base64 payload and the file is shown, and
    // downloaded, under a blob of base64.
    fieldDependencies: ({ attrs }) =>
        attrs.filename ? [{ name: attrs.filename, optional: true, written: true }] : [],
    extractProps: ({ attrs, options }) => ({
        acceptedFileExtensions: options.accepted_file_extensions,
        allowedMIMETypes: options.allowed_mime_type,
        fileNameField: attrs.filename,
    }),
};

export const listBinaryField = {
    ...binaryField,
    component: ListBinaryField,
};

registerField("binary", binaryField);
registerField({ name: "binary", view: "list" }, listBinaryField);
