/** @odoo-module native */
import { FileModel } from "@web/components/file_viewer";

export class CheckAttachment extends FileModel {
    constructor(fileData) {
        super();
        this.data = fileData;
        for (const property of [
            "access_token",
            "checksum",
            "extension",
            "filename",
            "id",
            "mimetype",
            "name",
            "type",
            "tmpUrl",
            "url",
            "uploading",
        ]) {
            this[property] = this.data[property];
        }
    }
}
