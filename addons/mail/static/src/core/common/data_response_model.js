/** @odoo-module native */
import { fields, Record } from "@mail/core/common/record";
import { Deferred } from "@web/core/utils/concurrency";
export class DataResponse extends Record {
    static id = "id";
    static _lastId = 0;

    static createRequest() {
        return this.insert({ id: ++this._lastId });
    }

    /** @type {number} */
    id;
    _autoResolve = false;
    _resultDef = new Deferred();
    /** @type {boolean} */
    _resolve = fields.Attr(undefined, {
        /** @this {import("models").DataResponse} */
        onUpdate() {
            if (this._resolve) {
                this._resultDef.resolve({ ...this });
                this.delete();
            }
        },
    });
    attachments = fields.Many("ir.attachment");
    channel = fields.One("Thread");
    channels = fields.Many("Thread");
    /** @type {number} */
    count;
    message = fields.One("mail.message");
    partners = fields.Many("res.partner");
}

DataResponse.register();
