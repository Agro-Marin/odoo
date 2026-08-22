/** @odoo-module native */
import { registry } from "@web/core/registry";

export const uploadLocalFileService = {
    dependencies: ["upload", "orm"],
    start(env, { upload: uploadService, orm }) {
        const input = document.createElement("input");
        input.type = "file";

        /**
         * @param {Object} [options]
         * @param {boolean} [options.multiple]
         * @param {string} [options.accept]
         * @returns {Promise<FileList>}
         */
        async function selectLocalFiles({ multiple, accept }) {
            input.multiple = multiple;
            input.accept = accept;
            input.value = "";

            input.click();

            await new Promise((resolve) => {
                const resolveAndClear = () => {
                    resolve();
                    input.removeEventListener("change", resolveAndClear);
                    input.removeEventListener("cancel", resolveAndClear);
                };
                input.addEventListener("change", resolveAndClear);
                input.addEventListener("cancel", resolveAndClear);
            });
            return input.files;
        }

        /**
         * @param {FileList} files
         * @param {Object} recordInfo
         * @param {Function} setAbortCallback
         * @returns {Promise<Object[]>}
         */
        async function filesToAttachments(
            files,
            { resModel, resId },
            setAbortCallback,
        ) {
            const attachments = [];
            await uploadService.uploadFiles(
                files,
                { resModel, resId },
                (attachment) => {
                    attachments.push(attachment);
                },
                setAbortCallback,
            );
            return attachments;
        }

        /**
         * @param {Object} recordInfo
         * @param {Object} [options]
         * @param {string} [options.accept]
         * @param {boolean} [options.multiple=false]
         * @param {boolean} [options.accessToken=false]
         * @param {Function} [options.setAbortCallback=()=>{}]
         * @returns {Promise<Object[]>}
         */
        async function upload(
            { resId, resModel },
            {
                accept = "*/*",
                multiple = false,
                accessToken = false,
                setAbortCallback = () => {},
            } = {},
        ) {
            try {
                const files = await selectLocalFiles({ multiple, accept });
                const attachments = await filesToAttachments(
                    files,
                    { resModel, resId },
                    setAbortCallback,
                );
                if (accessToken && attachments.length && !attachments[0].public) {
                    await addAccessToken(attachments);
                }
                return attachments;
            } catch {
                return [];
            }
        }

        /**
         * @param {Object[]} attachments
         * @returns {Promise<Object[]>}
         */
        async function addAccessToken(attachments) {
            const accessTokens = await orm.call(
                "ir.attachment",
                "generate_access_token",
                [attachments.map((a) => a.id)],
            );
            attachments.forEach((attachment, index) => {
                attachment.access_token = accessTokens[index];
            });
            return attachments;
        }

        /**
         * @param {Object} attachment
         * @param {Object} [options]
         * @returns {string}
         */
        function getURL(attachment, { unique, download, accessToken } = {}) {
            let url = `/web/content/${attachment.id}`;
            const queryParams = [];
            if (unique) {
                queryParams.push(`unique=${encodeURIComponent(attachment.checksum)}`);
            }
            if (download) {
                queryParams.push("download=true");
            }
            if (accessToken && attachment.access_token) {
                queryParams.push(`access_token=${attachment.access_token}`);
            }
            if (queryParams.length) {
                url += `?${queryParams.join("&")}`;
            }
            return url;
        }

        return { upload, addAccessToken, getURL };
    },
};

registry.category("services").add("uploadLocalFiles", uploadLocalFileService);
