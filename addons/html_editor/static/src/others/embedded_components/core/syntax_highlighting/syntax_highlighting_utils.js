/** @odoo-module native */
import { fillEmpty } from "@html_editor/utils/dom";
import { descendants, lastLeaf } from "@html_editor/utils/dom_traversal";

export const DEFAULT_LANGUAGE_ID = "plaintext";

/**
 * @param {Element} element
 * @param {Document} [doc = element.ownerDocument || document]
 */
export const newlinesToLineBreaks = (
    element,
    doc = element.ownerDocument || document,
) => {
    for (const node of descendants(element).filter(
        (node) => node.nodeType === Node.TEXT_NODE,
    )) {
        let newline = node.textContent.indexOf("\n");
        while (newline !== -1) {
            node.before(doc.createTextNode(node.textContent.slice(0, newline)));
            node.before(doc.createElement("BR"));
            node.textContent = node.textContent.slice(newline + 1);
            newline = node.textContent.indexOf("\n");
        }
        if (!node.textContent) {
            node.remove();
        }
    }
    const trailingBr = lastLeaf(element);
    if (trailingBr?.nodeName === "BR") {
        element.append(trailingBr);
        trailingBr.after(doc.createElement("BR"));
    }
    fillEmpty(element);
};

/**
 * @param {HTMLPreElement} pre
 * @returns {string}
 */
export const getPreValue = (pre) => {
    const html = pre.innerHTML;
    const hasTrailingBr = /<br\s*\/?>$/i.test(html);
    let text = html
        .replace(/<br\s*\/?>/gi, "\n")
        .replace(/<span\b[^>]*\bclass=["']oe-tabs["'][^>]*>.*?<\/span>/gi, "    ")
        .replace(/<[^>]+>|[\u200B\uFEFF]/g, "")
        .replace(
            /&(amp|lt|gt|#x27|quot|#x60|nbsp);/g,
            (_, entity) =>
                ({
                    amp: "&",
                    lt: "<",
                    gt: ">",
                    "#x27": "'",
                    quot: '"',
                    "#x60": "`",
                    nbsp: " ",
                })[entity],
        );
    if (hasTrailingBr && text.endsWith("\n")) {
        text = text.slice(0, -1);
    }
    return text;
};

/**
 * @param {HTMLPreElement} pre
 * @param {string} value
 * @param {string} languageId
 */
export const highlightPre = (pre, value, languageId) => {
    const fakeElement = pre.ownerDocument.createElement("pre");
    if (window.Prism) {
        fakeElement.innerHTML = Prism.highlight(
            value,
            Prism.languages[languageId],
            languageId,
        );
    } else {
        fakeElement.innerHTML = value;
    }

    newlinesToLineBreaks(fakeElement, pre.ownerDocument);

    [...pre.childNodes].forEach((child) => child.remove());
    [...fakeElement.childNodes].forEach((child) => pre.append(child));
};
