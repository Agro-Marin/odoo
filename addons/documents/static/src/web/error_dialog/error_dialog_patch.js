/** @odoo-module native */
import { browser } from "@web/core/browser/browser";
import { ErrorDialog } from "@web/components/errors";
import { _t } from "@web/core/translation";
import { useBus, useService } from "@web/core/utils/hooks";
import { CopyButton } from "@web/components/copy_button";

import { patch } from "@web/core/utils/patch";
import * as luxon from "luxon";

patch(ErrorDialog.components, {
    CopyButton,
});

const TRACEBACK_MARKER = "documents_traceback";

patch(ErrorDialog.prototype, {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.fileUpload = useService("file_upload");
        this.dialogService = useService("dialog");
        this.documentService = useService("document.document");
        this.notification = useService("notification");
        this.state.tracebackUrl = null;
        this.state.processed = false;
        useBus(this.fileUpload.bus, "FILE_UPLOAD_LOADED", async (ev) => {
            const { upload } = ev.detail;
            if (!upload.data?.get(TRACEBACK_MARKER)) {
                return;
            }
            if (upload.xhr.status === 200 && this.state.processed) {
                const response = JSON.parse(upload.xhr.response);
                if (response.length === 1) {
                    this.state.tracebackUrl = response[0];
                    setTimeout(async () => {
                        await browser.navigator.clipboard.writeText(response[0]);
                        this.notification.add(_t("The document URL has been copied to your clipboard."), {
                            type: "success"
                        });
                    });
                }
            }
        });
    },
    shareTraceback() {
        if (!this.state.processed) {
            this.state.processed = true;
            const file = new File(
                [
                    `${this.props.name}\n\n${this.props.message}\n\n${this.contextDetails}\n\n${
                        this.traceback || this.props.traceback
                    }`,
                ],
                `${this.constructor.title} - ${luxon.DateTime.local().toFormat(
                    "yyyy-MM-dd HH:mm:ss"
                )}.txt`,
                { type: "text/plain" }
            );
            const markPayload = (formData) => formData.append(TRACEBACK_MARKER, "1");
            this.fileUpload.upload("/documents/upload_traceback", [file], {
                buildFormData: markPayload,
            });
        }
    },
});
