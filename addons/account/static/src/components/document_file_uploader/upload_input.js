/** @odoo-module native */
import { _t } from "@web/core/translation";

// The class `DocumentFileUploader` gives its FileUploader's <input type="file">.
const UPLOAD_INPUT_SELECTOR = ".document_file_uploader.o_input_file";

/**
 * Mimetypes a paste may carry into the uploader.
 *
 * Narrower than what the server's import pipeline tolerates
 * (`account_document_import_mixin._should_attach_to_record`), on purpose: Ctrl+V
 * is easy to hit with a screenshot on the clipboard, and a dropped file is a
 * deliberate act where the same restriction would refuse the images enterprise
 * OCR reads. Widening this is a product decision, not a cleanup.
 */
export const PASTEABLE_MIMETYPES = ["text/xml", "application/pdf"];

/**
 * Hand a DataTransfer's files to a document uploader input, the way choosing them
 * in the file dialog would.
 *
 * @param {DataTransfer} dataTransfer
 * @param {Object} [options]
 * @param {HTMLElement} [options.scopeEl] search here first, so a drop reaches the
 *  input beside it — which may carry a different context — before any other
 * @param {string[]} [options.acceptedMimetypes] refuse the whole batch unless
 *  every item matches; unset accepts whatever the server will
 * @param {Object} [options.notification] notification service, to say why not
 * @returns {boolean} whether the files reached an input
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
        // A plain-text paste, or a drag that carried no file: nothing to extract.
        return warn("No file to hand to the document uploader.");
    }
    if (acceptedMimetypes) {
        const refused = [...dataTransfer.items].filter(
            (item) => item.kind !== "file" || !acceptedMimetypes.includes(item.type),
        );
        if (refused.length) {
            // All or nothing: a batch is one document set, and uploading half of
            // it silently is worse than uploading none of it loudly.
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
