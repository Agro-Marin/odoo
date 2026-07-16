// @ts-check
/** @odoo-module native */

/** @module @web/fields/media/binary/binary_field - File upload/download field for Binary columns */

import { Component } from "@odoo/owl";
import { FileUploader } from "@web/core/file_upload/file_handler";
import { _t } from "@web/core/l10n/translation";
import { download } from "@web/core/network/download";
import { isBinarySize, toBase64Length } from "@web/core/utils/format/binary";
import { useService } from "@web/core/utils/hooks";
import { registerField } from "@web/fields/_registry";
import { standardFieldProps } from "@web/fields/standard_field_props";

export const MAX_FILENAME_SIZE_BYTES = 0xff; // filenames do not exceed 255 bytes on Linux/Windows/MacOS

const textEncoder = new TextEncoder();

/**
 * Truncates a string to at most `maxBytes` UTF-8 bytes without splitting a
 * multi-byte character. `String.prototype.slice` counts UTF-16 code units, so a
 * name of multibyte characters could exceed the byte cap.
 *
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
        // See https://www.iana.org/assignments/media-types/media-types.xhtml
        allowedMIMETypes: { type: String, optional: true },
        fileNameField: { type: String, optional: true },
    };
    static defaultProps = {
        acceptedFileExtensions: "*",
    };

    setup() {
        this.notification = useService("notification");
    }

    /** @returns {string} Display filename, truncated to max filesystem length */
    get fileName() {
        const fileName = this.props.record.data[this.props.fileNameField];
        if (fileName) {
            return truncateToByteLength(fileName, MAX_FILENAME_SIZE_BYTES);
        }
        // Fallback: the base64 content stands in for the name; slice at the
        // base64 length whose decoded size fits the filename limit.
        let value = this.props.record.data[this.props.name];
        value = value && typeof value === "string" ? value : "";
        return value.slice(0, toBase64Length(MAX_FILENAME_SIZE_BYTES));
    }

    /**
     * @param {{ data: string|false, name: string }} payload Uploaded file data and name
     * @returns {Promise} Record update promise
     */
    update({ data, name }) {
        const { fileNameField, record } = this.props;
        const changes = { [this.props.name]: data || false };
        if (fileNameField in record.fields && record.data[fileNameField] !== name) {
            changes[fileNameField] = name || "";
        }
        return this.props.record.update(changes);
    }

    /** @returns {Object} Parameters for the /web/content download endpoint */
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

    /** Triggers a browser download of the binary field content */
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
