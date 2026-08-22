/** @odoo-module native */
import { DocumentSelector } from "@html_editor/main/media/media_dialog/document_selector";
import { renderToElement } from "@web/core/utils/render";

export class EmbeddedFileDocumentsSelector extends DocumentSelector {
    static mediaSpecificClasses = [];

    /** @override */
    static async renderFileElement(attachment) {
        return renderEmbeddedFileBox(attachment);
    }
}

/**
 * @param {Object} attachment
 * @returns {Element}
 */
export function renderEmbeddedFileBox(attachment) {
    const dotSplit = attachment.name.split(".");
    const extension = dotSplit.length > 1 ? dotSplit.pop() : undefined;
    const fileData = {
        access_token: attachment.access_token,
        checksum: attachment.checksum,
        extension,
        filename: attachment.name,
        id: attachment.id,
        mimetype: attachment.mimetype,
        name: attachment.name,
        type: attachment.type,
        url: attachment.url || "",
    };
    return renderToElement("html_editor.EmbeddedFileBlueprint", {
        embeddedProps: JSON.stringify({ fileData }),
    });
}
