/** @odoo-module native */
// Supported file types we need extract on paste
const supportedFileTypes = ["text/xml", "application/pdf"];

/**
 * Return function to extract and upload from given dataTransfer.
 *
 * @param {dataTransfer} dataTransfer containing text or files.
 */
export function uploadFileFromData() {
    return async (dataTransfer) => {

        function uploadFiles(dataTransfer) {
            const invalidFiles = [...dataTransfer.items].filter(
                (item) => item.kind !== "file" || !supportedFileTypes.includes(item.type)
            );
            if (invalidFiles.length !== 0) {
                // don't upload any files if one of them is non supported file type
                console.warn("Invalid files to extract details.");
                return;
            }
            const uploadInput = document.querySelector('.document_file_uploader.o_input_file');
            if (!uploadInput) {
                // The uploader input is not in the DOM (e.g. upload button hidden).
                console.warn("No file uploader available to receive the pasted files.");
                return;
            }
            uploadInput.files = dataTransfer.files;
            uploadInput.dispatchEvent(new Event("change"));
        }

        if (dataTransfer.files.length !== 0) {
            uploadFiles(dataTransfer);
        } else {
            console.warn("Invalid data to extract details.");
        }
    }
}
