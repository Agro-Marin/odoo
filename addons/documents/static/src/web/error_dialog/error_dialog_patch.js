/** @odoo-module native */
import { browser } from "@web/core/browser/browser";
import { ErrorDialog } from "@web/components/errors/error_dialogs";
import { _t } from "@web/core/l10n/translation";
import { useBus, useService } from "@web/core/utils/hooks";
import { CopyButton } from "@web/components/copy_button/copy_button";

import { patch } from "@web/core/utils/patch";
import * as luxon from "luxon";

patch(ErrorDialog.components, {
    CopyButton,
});

/**
 * Form-data marker identifying the traceback upload as this dialog's own.
 *
 * `file_upload`'s bus is application-wide, so `FILE_UPLOAD_LOADED` fires for
 * every upload in the session -- including a documents upload the user started
 * before the error appeared. `/documents/upload/<token>` answers with an array
 * of new document ids, so a single-file upload is shape-identical to the
 * traceback controller's `[url]` response and used to be adopted here: the
 * dialog published a document id as its "traceback URL" and copied it to the
 * clipboard announcing "The document URL has been copied to your clipboard."
 */
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
                return; // someone else's upload -- see TRACEBACK_MARKER
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
