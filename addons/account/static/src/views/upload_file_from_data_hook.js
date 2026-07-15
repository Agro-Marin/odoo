/** @odoo-module native */
import { _t } from "@web/core/l10n/translation";

// Supported file types we need extract on paste
const supportedFileTypes = ["text/xml", "application/pdf"];

/**
 * Return a function that extracts and uploads the files from a pasted/dropped
 * dataTransfer. Failures are logged and, when a notification service is passed,
 * surfaced to the user (the paste path had no user feedback before).
 *
 * @param {Object} [notification] the "notification" service (optional)
 * @returns {(dataTransfer: DataTransfer) => Promise<void>}
 */
export function uploadFileFromData(notification) {
    const warn = (logMessage, userMessage) => {
        console.warn(logMessage);
        if (userMessage) {
            notification?.add(userMessage, { type: "warning" });
        }
    };

    return async (dataTransfer) => {
        function uploadFiles(dataTransfer) {
            const invalidFiles = [...dataTransfer.items].filter(
                (item) => item.kind !== "file" || !supportedFileTypes.includes(item.type)
            );
            if (invalidFiles.length !== 0) {
                // don't upload any files if one of them is non supported file type
                warn(
                    "Invalid files to extract details.",
                    _t("Only PDF and XML files can be pasted here."),
                );
                return;
            }
            const uploadInput = document.querySelector('.document_file_uploader.o_input_file');
            if (!uploadInput) {
                // The uploader input is not in the DOM (e.g. upload button hidden).
                warn("No file uploader available to receive the pasted files.");
                return;
            }
            uploadInput.files = dataTransfer.files;
            uploadInput.dispatchEvent(new Event("change"));
        }

        if (dataTransfer.files.length !== 0) {
            uploadFiles(dataTransfer);
        } else {
            // No files (e.g. a plain-text paste): nothing to extract, stay silent
            // for the user but log for debugging.
            warn("Invalid data to extract details.");
        }
    };
}
