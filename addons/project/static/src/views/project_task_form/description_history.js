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
 * Open the version history of a project.task description, and restore a
 * revision from it if the user asks for one.
 *
 * The To-Do app shows the same feature on the same model behind its own
 * wording, so this lives here rather than in either form controller: the two
 * copies drifted once already, and only one of them was repaired.
 *
 * @param {Object} params
 * @param {Object} params.record the form's root record
 * @param {string} params.resModel
 * @param {Object} params.dialogService
 * @param {Object} params.notificationService
 * @param {string} params.title dialog title
 * @param {string} params.emptyLabel shown for a revision whose content was empty
 * @param {string} params.noHistoryMessage notification when there is nothing to restore
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
                    // Carry `data-last-history-steps` over from the current
                    // value: a revision is old html that no longer holds it,
                    // and writing it back bare severs the chain this dialog
                    // reads from.
                    const contentMetadata = getHtmlFieldMetadata(
                        record.data[VERSIONED_FIELD_NAME],
                    );
                    // Await so a failed restore surfaces in this dialog instead
                    // of as an unhandled rejection after everything closed.
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
