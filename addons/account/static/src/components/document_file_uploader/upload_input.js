/** @odoo-module native */
import { _t } from "@web/core/translation";

const UPLOAD_INPUT_SELECTOR = ".document_file_uploader.o_input_file";

export const PASTEABLE_MIMETYPES = ["text/xml", "application/pdf"];

/**
 * @param {DataTransfer} dataTransfer
 * @param {Object} [options]
 * @param {HTMLElement} [options.scopeEl]
 * @param {string[]} [options.acceptedMimetypes]
 * @param {Object} [options.notification]
 * @returns {boolean}
 */
export function sendFilesToUploadInput(
    dataTransfer,
    { scopeEl, acceptedMimetypes, notification } = {},
) {
    const warn = (logMessage, userMessage, type = "warning") => {
        console.warn(logMessage);
        if (userMessage) {
            notification?.add(userMessage, { type });
        }
        return false;
    };

    if (!dataTransfer?.files?.length) {
        return warn("No file to hand to the document uploader.");
    }
    if (acceptedMimetypes) {
        const refused = [...dataTransfer.items].filter(
            (item) => item.kind !== "file" || !acceptedMimetypes.includes(item.type),
        );
        if (refused.length) {
            return warn(
                "Unsupported file type for the document uploader.",
                _t("Only PDF and XML files can be pasted here."),
            );
        }
    }

    const uploadInput =
        scopeEl?.querySelector(UPLOAD_INPUT_SELECTOR) ||
        document.querySelector(UPLOAD_INPUT_SELECTOR);
    if (!uploadInput) {
        return warn(
            "No document uploader input in the page to receive the files.",
            _t("Could not upload files"),
            "danger",
        );
    }
    uploadInput.files = dataTransfer.files;
    uploadInput.dispatchEvent(new Event("change"));
    return true;
}
