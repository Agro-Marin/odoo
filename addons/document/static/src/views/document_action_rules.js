/** @odoo-module native */
// @ts-check

/**
 * What a document allows, answered the same way for a search-panel folder
 * value (the cog menu) and for a list row's record data (the row widget). The
 * two used to encode each action twice with different rules.
 *
 * @param {import("@document/core/document_service").DocumentService} documentService
 * @param {Object} data a `document.document` read: id, type, active, ...
 */
export const documentActionRules = {
    rename: (documentService, data) =>
        data.active !== false && documentService.isEditable(data),
    share: (documentService, data) =>
        data.active !== false && documentService.isFolderSharable(data),
    download: (documentService, data) =>
        documentService.canDownload(data) &&
        (data.type !== "binary" || Boolean(data.attachment_id)),
    details: (documentService, data) =>
        documentService.userIsInternal && typeof data.id === "number",
};
