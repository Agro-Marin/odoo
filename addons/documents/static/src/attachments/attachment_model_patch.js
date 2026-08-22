/** @odoo-module native */
import { Attachment } from "@mail/core/common/attachment_model";
import { patch } from "@web/core/utils/patch";

const textMimeTypePattern = /^text\//;
const additionalMimeTypes = ["application/xml"];
const excludedMimeTypes = ["text/html", "text/csv"];

/** @type {import("models").Attachment} */
const attachmentPatch = {
    get urlRoute() {
        if (this.documentId) {
            return this.isImage
                ? `/web/image/${this.documentId}`
                : `/web/content/${this.documentId}`;
        }
        return super.urlRoute;
    },

    get defaultSource() {
        if (this.isPdf && this.documentId) {
            const encodedRoute = encodeURIComponent(
                `/documents/content/${encodeURIComponent(
                    this.documentData.access_token
                )}?download=0`
            );
            return `/web/static/lib/pdfjs/web/viewer.html?file=${encodedRoute}#pagemode=none`;
        }
        return super.defaultSource;
    },

    get urlQueryParams() {
        const res = super.urlQueryParams;
        if (this.documentId) {
            res["model"] = "documents.document";
            return res;
        }
        return res;
    },

    get isDocumentEmail() {
        return this.documentId && this.mimetype === "application/documents-email";
    },

    get isHtml() {
        return this.mimetype && this.mimetype.startsWith("text/html");
    },

    get isJson() {
        return this.mimetype && this.mimetype.startsWith("application/json");
    },

    get isMimetypeTextual() {
        return (
            this.documentId &&
            this.mimetype &&
            (additionalMimeTypes.includes(this.mimetype) ||
                (textMimeTypePattern.test(this.mimetype) &&
                    !excludedMimeTypes.some((type) => this.mimetype.startsWith(type))))
        );
    },

    documentEmailContent: null,
    documentTextContent: null,

    async loadDocumentEmailContent() {
        this.documentEmailContent = await this.store.env.services[
            "document.document"
        ].loadEmailContent(this.documentId);
    },
    async loadDocumentTextContent() {
        const response = await fetch(this.defaultSource);
        const result = await response.text();
        const escapedResult = result
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");
        this.documentTextContent = `<pre style="white-space: pre-wrap; word-wrap: break-word;">${escapedResult}</pre>`;
    },
};
patch(Attachment.prototype, attachmentPatch);
