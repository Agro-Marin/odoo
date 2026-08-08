/** @odoo-module native */
import { _t } from "@web/core/translation";
import { Mutex } from "@web/core/utils/concurrency";
import { checkFileSize } from "@web/core/utils/files";

export class BinaryFileManager {
    constructor(resModel, fields, parameters, context, orm, notificationService) {
        this.resModel = resModel;
        this.fields = [".id", ...fields];
        this.parameters = parameters;

        this.context = context;
        this.orm = orm;
        this.notificationService = notificationService;

        this.maxBatchSize = this.parameters.maxBatchSize * 0.95; // 0.95 for not calculated payload overhead
        this.delayAfterEachBatch = this.parameters.delayAfterEachBatch * 1000;

        this.dataToSend = {};
        // Running total of the pending payload. `getCurrentSize()` used to
        // JSON.stringify the whole `dataToSend` on every added file, so building
        // one batch cost O(n^2) in serialisation -- up to `maxBatchSize` bytes
        // re-serialised per file.
        this.currentSize = 0;

        this.mutex = new Mutex();
    }

    async addFile(id, field, file) {
        let data = await this._readFile(file);
        if (typeof data === "string" && data.startsWith("data:")) {
            // Remove data:image/*;base64,
            data = data.split(",")[1];
        }
        // Check against the real byte size (`file.size`), not the base64-encoded
        // string length used below for batch-size accounting: base64 inflates
        // size by ~1.33x, so comparing `data.length` to the byte-denominated
        // `session.max_file_upload_size` used to reject valid files between
        // ~75% and 100% of the real limit (t24068 F5).
        if (!checkFileSize(file.size, this.notificationService)) {
            return;
        }
        const dataSize = data.length;

        // Resolve the column before mutating anything: an unknown field name
        // yields -1, and `row[-1] = data` silently sets a stray property on the
        // array instead of a cell, dropping the file without a word.
        const indexOfField = this.fields.indexOf(field, 1);
        if (indexOfField === -1) {
            this.notificationService.add(
                _t("Unknown binary field %(field)s, its files were not uploaded.", {
                    field,
                }),
                { type: "danger" }
            );
            return;
        }

        if (this.getCurrentSize() + dataSize >= this.maxBatchSize) {
            await this.mutex.exec(async () => await this._send());
        }
        if (!(id in this.dataToSend)) {
            this.dataToSend[id] = Array(this.fields.length);
            this.dataToSend[id][0] = id;
        }
        this.dataToSend[id][indexOfField] = data;
        this.currentSize += dataSize;
    }

    async sendLastPayload() {
        if (Object.keys(this.dataToSend).length > 0) {
            await this.mutex.exec(async () => await this._send());
        }
    }

    async _send() {
        await new Promise((resolve) => {
            setTimeout(resolve, this.delayAfterEachBatch);
        });
        const data = Object.values(this.dataToSend);
        this.dataToSend = {};
        this.currentSize = 0;
        const context = {
            ...this.context,
            import_file: true,
            tracking_disable: this.parameters.tracking_disable,
            name_create_enabled_fields: this.parameters.name_create_enabled_fields || {},
            import_set_empty_fields: this.parameters.import_set_empty_fields || [],
            import_skip_records: this.parameters.import_skip_records || [],
        };
        let res;
        try {
            res = await this.orm.call(this.resModel, "load", [], {
                fields: this.fields,
                data,
                context,
            });
        } catch (error) {
            console.error(error);
            // The record import itself already reported success by this point
            // (this batch runs after `execute_import`); without this, an image/
            // attachment upload failure was completely silent to the user
            // (t24068 F3-frontend). Every caller still ignores the returned
            // `{error}` today (see the ledger for the fuller "annotate the
            // import summary" follow-up) — this notification is the one
            // user-visible signal in the meantime.
            this.notificationService.add(
                _t("Some binary/attachment fields could not be uploaded: %(error)s", {
                    error: error.message || error,
                }),
                { type: "danger" }
            );
            return { error };
        }
        return res;
    }

    _readFile(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onerror = (event) => reject(event);
            reader.onabort = (event) => reject(event);
            reader.onload = (event) => resolve(event.target.result);
            reader.readAsDataURL(file);
        });
    }

    getCurrentSize() {
        return this.currentSize;
    }
}
