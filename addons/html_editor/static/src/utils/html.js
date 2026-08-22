/** @odoo-module native */
/**
 * @param { Document } document
 * @param { string } html
 * @returns { DocumentFragment }
 */
export function parseHTML(document, html) {
    const fragment = document.createDocumentFragment();
    const parser = new document.defaultView.DOMParser();
    const parsedDocument = parser.parseFromString(html, "text/html");
    fragment.replaceChildren(...parsedDocument.body.childNodes);
    return fragment;
}

/**
 * @param { string } content
 * @param { function } cleanup
 * @returns { string }
 */
export function normalizeHTML(content, cleanup = () => {}) {
    const parser = new document.defaultView.DOMParser();
    const body = parser.parseFromString(content, "text/html").body;
    cleanup(body);
    return body.innerHTML;
}
