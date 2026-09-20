// @ts-check
/** @odoo-module native */
import { useState } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useService } from "@web/core/utils/hooks";

const log = makeLogger("mail.attachment_upload");
/**
 * @param {string} data
 * @param {string} type
 * @returns {Blob}
 */
export function dataUrlToBlob(data, type) {
    const binData = window.atob(data);
    const uiArr = new Uint8Array(binData.length);
    uiArr.forEach((_, index) => (uiArr[index] = binData.charCodeAt(index)));
    return new Blob([uiArr], { type });
}

export class AttachmentUploader {
    /**
     * @param {import("models").Thread} thread
     * @param {Object} [options]
     * @param {import("models").Composer} [options.composer]
     */
    constructor(thread, { composer } = {}) {
        this.attachmentUploadService = useService("mail.attachment_upload");
        this.thread = thread;
        this.composer = composer;
    }

    /**
     * @param {Object} file
     * @param {string} file.data
     * @param {string} file.name
     * @param {string} file.type
     * @param {Object} [options]
     * @returns {Promise<import("models").Attachment|undefined>}
     */
    uploadData({ data, name, type }, options) {
        const file = new File([dataUrlToBlob(data, type)], name, { type });
        return this.uploadFile(file, options);
    }

    /**
     * @param {File} file
     * @param {Object} [options]
     * @param {import("models").Activity} [options.activity]
     * @param {import("models").Thread} [options.thread]
     * @param {boolean} [options.voice]
     */
    async uploadFile(file, options) {
        const thread = options?.thread || this.thread;
        log.logic("uploadFile", () => ({
            thread: thread?.localId,
            composer: Boolean(this.composer),
            name: file.name,
            size: file.size,
            voice: options?.voice,
            activity: options?.activity?.id,
        }));
        return this.attachmentUploadService.upload(
            thread,
            this.composer,
            file,
            options,
        );
    }

    /** @param {import("models").Attachment} attachment */
    async unlink(attachment) {
        await this.attachmentUploadService.unlink(attachment);
    }
}

/**
 * @param {import("models").Thread} thread
 * @param {Object} [param1={}]
 * @param {import("models").Composer} [param1.composer]
 */
export function useAttachmentUploader(thread, { composer } = {}) {
    return useState(new AttachmentUploader(thread, { composer }));
}
