// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";
import { _t } from "@web/core/translation";

import { FileUploadProgressBar } from "./file_upload_progress_bar.js";
export class FileUploadProgressRecord extends Component {
    static components = {
        FileUploadProgressBar,
    };
    static props = {
        fileUpload: Object,
        selector: { type: String, optional: true },
    };
    /**
     * @returns {{ left: string, right: string }}
     */
    getProgressTexts() {
        const fileUpload = this.props.fileUpload;
        const percent = Math.round(fileUpload.progress * 100);
        if (percent === 100) {
            return {
                left: _t("Processing..."),
                right: "",
            };
        } else {
            const mbLoaded = Math.round(fileUpload.loaded / 1000000);
            const mbTotal = Math.round(fileUpload.total / 1000000);
            return {
                left: _t("Uploading... (%s%)", percent),
                right: _t("(%(mbLoaded)s/%(mbTotal)sMB)", {
                    mbLoaded,
                    mbTotal,
                }),
            };
        }
    }
}

export class FileUploadProgressKanbanRecord extends FileUploadProgressRecord {
    static template = "web.FileUploadProgressKanbanRecord";
}

export class FileUploadProgressDataRow extends FileUploadProgressRecord {
    static template = "web.FileUploadProgressDataRow";
}
