/** @odoo-module native */
/**
 * A previewable document: the datapoint the previewer was opened on, plus the
 * synthetic `ir.attachment` the web FileViewer renders.
 *
 * Only what is actually consumed: the previewer reads the attachment, every other
 * caller reads `record`.
 */
export class Document {
    /** Datapoint res id, and the key in `store.Document.records`. */
    id;
    /** @type {import("models").Attachment} */
    attachment;
    /** @type {Object} the `documents.document` datapoint */
    record;
}
