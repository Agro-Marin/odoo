// @ts-check
/** @odoo-module native */
import { fields, Record } from "@mail/core/common/record";
import { makeLogger } from "@web/core/debug/debug_logger";
import { Deferred } from "@web/core/utils/concurrency";

const log = makeLogger("mail.store");
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
                log.pipeline("request resolved", () => ({ id: this.id }));
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
