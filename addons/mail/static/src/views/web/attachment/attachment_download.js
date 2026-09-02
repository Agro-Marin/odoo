/** @odoo-module native */
import { serializeDate } from "@web/core/l10n/dates";
import { DateTime } from "@web/core/l10n/luxon";
import { download } from "@web/core/network/download";
import { _t } from "@web/core/translation";

/**
 * How many attachments one zip request may carry. The controller behind
 * `/mail/attachment/zip` allows 200 (`MAX_ZIP_ATTACHMENTS`); this lower bound is
 * about the wait, not about what the server accepts.
 */
export const MAX_DOWNLOAD_FILES = 20;

/**
 * Download the selected attachments: the file itself when there is one, a zip
 * when there are several. Only records of type `binary` have a file at all --
 * a `url` attachment is a link and there is nothing to put in the archive.
 *
 * Shared by the list and the kanban of `ir.attachment` rather than mixed into
 * their controllers, so that both keep a plain `extends ListController` /
 * `extends KanbanController` shape like every other view of this module.
 *
 * @param {import("@web/views/multi_record_controller").MultiRecordController} controller
 */
export async function downloadSelectedAttachments(controller) {
    const root = controller.model.root;
    const notification = controller.env.services.notification;
    const files = root.selection.filter((record) => record.data.type === "binary");
    if (files.length > MAX_DOWNLOAD_FILES) {
        notification.add(
            _t("You can only download %s files at a time.", MAX_DOWNLOAD_FILES),
            { type: "danger" },
        );
        return;
    }
    if (files.length < root.selection.length) {
        notification.add(_t("Only files will be downloaded."), { type: "warning" });
    }
    if (root.isDomainSelected) {
        notification.add(_t("Only the selected files will be downloaded."), {
            type: "warning",
        });
    }
    if (files.length === root.selection.length && !root.isDomainSelected) {
        notification.add(_t("Your download will start soon."), { type: "info" });
    }
    if (files.length === 1) {
        return download({ data: { id: files[0].resId }, url: "/web/content" });
    }
    return download({
        data: {
            file_ids: files.map((record) => record.resId),
            zip_name: `attachments-${serializeDate(DateTime.now())}.zip`,
        },
        url: "/mail/attachment/zip",
    });
}

/**
 * The "Download" entry of the action menu, ready to be merged into whatever
 * `getStaticActionMenuItems` returned. It is added after that call and not
 * through `buildStaticActionMenuItems`, whose descriptors live in `addons/web`.
 *
 * @param {import("@web/views/multi_record_controller").MultiRecordController} controller
 */
export function attachmentDownloadMenuItem(controller) {
    return {
        callback: () => downloadSelectedAttachments(controller),
        description: _t("Download"),
        icon: "fa-solid fa-download",
        isAvailable: () =>
            controller.model.root.selection.some(
                (record) => record.data.type === "binary",
            ),
        sequence: 15,
    };
}
