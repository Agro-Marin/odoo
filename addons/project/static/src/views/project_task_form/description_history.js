/** @odoo-module native */
import { HistoryDialog } from "@html_editor/components/history_dialog/history_dialog";
import {
    getHtmlFieldMetadata,
    setHtmlFieldMetadata,
} from "@html_editor/fields/html_field";
import { markup } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { ConfirmationDialog } from "@web/ui/dialog";

const VERSIONED_FIELD_NAME = "description";

/**
 * @param {Object} params
 * @param {Object} params.record
 * @param {string} params.resModel
 * @param {Object} params.dialogService
 * @param {Object} params.notificationService
 * @param {string} params.title
 * @param {string} params.emptyLabel
 * @param {string} params.noHistoryMessage
 */
export function openDescriptionHistoryDialog({
    record,
    resModel,
    dialogService,
    notificationService,
    title,
    emptyLabel,
    noHistoryMessage,
}) {
    const historyMetadata =
        record.data["html_field_history_metadata"]?.[VERSIONED_FIELD_NAME];
    if (!historyMetadata) {
        notificationService.add(noHistoryMessage);
        return;
    }

    dialogService.add(HistoryDialog, {
        title,
        noContentHelper: markup`<span class='text-muted fst-italic'>${emptyLabel}</span>`,
        recordId: record.resId,
        recordModel: resModel,
        versionedFieldName: VERSIONED_FIELD_NAME,
        historyMetadata,
        restoreRequested: (html, close) => {
            dialogService.add(ConfirmationDialog, {
                title: _t("Are you sure you want to restore this version?"),
                body: _t(
                    "Restoring will replace the current content with the selected version. Any unsaved changes will be lost.",
                ),
                confirm: async () => {
                    const contentMetadata = getHtmlFieldMetadata(
                        record.data[VERSIONED_FIELD_NAME],
                    );
                    await record.update({
                        [VERSIONED_FIELD_NAME]: setHtmlFieldMetadata(
                            html,
                            contentMetadata,
                        ),
                    });
                    close();
                },
                confirmLabel: _t("Restore"),
            });
        },
    });
}
