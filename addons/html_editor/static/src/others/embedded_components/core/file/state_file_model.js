/** @odoo-module native */
import { FileModel } from "@web/components/file_viewer";

export class StateFileModel extends FileModel {
    constructor(state) {
        super();
        this.state = state;
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
            Object.defineProperty(this, property, {
                get() {
                    return this.state.fileData[property];
                },
                set(value) {
                    this.state.fileData[property] = value;
                },
                configurable: true,
                enumerable: true,
            });
        }
    }

    /**
     * @override
     */
    get urlRoute() {
        if (this.isUrl && !this.id) {
            return this.url;
        }
        return super.urlRoute;
    }
}
