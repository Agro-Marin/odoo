/** @odoo-module native */
import {
    baseContainerGlobalSelector,
    getBaseContainerSelector,
} from "@html_editor/utils/base_container";

import { Plugin } from "../plugin.js";
import { closestBlock } from "../utils/blocks.js";
import { fillHtmlTransferData } from "../utils/clipboard.js";
import {
    fillEmpty,
    splitTextNode,
    unwrapContents,
    wrapInlinesInBlocks,
} from "../utils/dom.js";
import {
    isContentEditable,
    isEmptyBlock,
    isParagraphRelatedElement,
    isTextNode,
} from "../utils/dom_info.js";
import { childNodes, closestElement } from "../utils/dom_traversal.js";
import { parseHTML } from "../utils/html.js";
import { DIRECTIONS } from "../utils/position.js";
import { isHtmlContentSupported } from "./selection_plugin.js";

/**
 * @typedef { import("./selection_plugin").EditorSelection } EditorSelection
 * @typedef {(() => boolean)[]} bypass_paste_image_files
 */

const CLIPBOARD_BLACKLISTS = {
    unwrap: [
        ".Apple-interchange-newline",
        "DIV",
    ],
    remove: ["META", "STYLE", "SCRIPT"],
};
export const CLIPBOARD_WHITELISTS = {
    nodes: [
        "P",
        "H1",
        "H2",
        "H3",
        "H4",
        "H5",
        "H6",
        "BLOCKQUOTE",
        "PRE",
        "UL",
        "OL",
        "LI",
        "I",
        "B",
        "U",
        "S",
        "EM",
        "FONT",
        "STRONG",
        "TABLE",
        "THEAD",
        "TH",
        "TBODY",
        "TR",
        "TD",
        "IMG",
        "BR",
        "A",
        ".fa",
    ],
    classes: [
        /^float-/,
        "d-block",
        "mx-auto",
        "img-fluid",
        "img-thumbnail",
        "rounded",
        "rounded-circle",
        "o_table",
        "table",
        "table-bordered",
        /^padding-/,
        /^shadow/,
        /^text-o-/,
        /^bg-o-/,
        "o_checked",
        "o_checklist",
        "oe-nested",
        /^btn/,
        /^fa/,
    ],
    attributes: ["class", "href", "src", "target"],
    styledTags: ["SPAN", "B", "STRONG", "I", "S", "U", "FONT", "TD"],
};

const ONLY_LINK_REGEX = /^(https?:\/\/)?([\w-]+\.)+[\w-]+(\/[\w-./?%&=]*)?$/i;

/**
 * @typedef {Object} ClipboardShared
 * @property {ClipboardPlugin['pasteText']} pasteText
 */

/**
 * @typedef {((img: HTMLImageElement) => void)[]} added_image_handlers
 * @typedef {(() => void)[]} after_paste_handlers
 * @typedef {(() => void)[]} before_paste_handlers
 * @typedef {((selection: EditorSelection, text: string) => boolean)[]} paste_text_overrides
 * @typedef {((
 * clonedContents: DocumentFragment,
 * selection: EditorSelection
 * ) => void | clonedContents)[]} clipboard_content_processors
 * @typedef {((textContent: string) => string)[]} clipboard_text_processors
 */

export class ClipboardPlugin extends Plugin {
    static id = "clipboard";
    static dependencies = [
        "baseContainer",
        "dom",
        "selection",
        "sanitize",
        "history",
        "split",
        "delete",
        "lineBreak",
    ];
    static shared = ["pasteText"];

    setup() {
        this.addDomListener(this.editable, "copy", this.onCopy);
        this.addDomListener(this.editable, "cut", this.onCut);
        this.addDomListener(this.editable, "paste", this.onPaste);
        this.addDomListener(this.editable, "dragstart", this.onDragStart);
        this.addDomListener(this.editable, "drop", this.onDrop);
    }

    onCut(ev) {
        const selection = this.dependencies.selection.getEditableSelection();
        this.dispatchTo("before_cut_handlers", selection);
        this.onCopy(ev);
        this.dependencies.history.stageSelection();
        this.dependencies.delete.deleteSelection();
        this.dependencies.history.addStep();
    }

    /**
     * @param {ClipboardEvent} ev
     */
    onCopy(ev) {
        ev.preventDefault();
        this.setSelectionTransferData(ev, "clipboardData");
    }

    setSelectionTransferData(ev, transferObjectProperty) {
        const selection = this.dependencies.selection.getEditableSelection();
        let clonedContents = selection.cloneContents();
        if (!clonedContents.hasChildNodes()) {
            return;
        }
        let textContent = selection.textContent();
        for (const processor of this.getResource("clipboard_text_processors")) {
            textContent = processor(textContent);
        }

        for (const processor of this.getResource("clipboard_content_processors")) {
            clonedContents = processor(clonedContents, selection) || clonedContents;
        }
        this.dependencies.dom.removeSystemProperties(clonedContents);
        fillHtmlTransferData(ev, transferObjectProperty, clonedContents, {
            setEditorTransferData:
                isContentEditable(selection.commonAncestorContainer) ||
                this.dependencies.selection.isNodeEditable(
                    selection.commonAncestorContainer,
                ),
            textContent,
        });
    }

    onPaste(ev) {
        let selection = this.dependencies.selection.getEditableSelection();
        if (
            !selection.anchorNode.isConnected ||
            !closestElement(selection.anchorNode).isContentEditable
        ) {
            return;
        }
        ev.preventDefault();

        this.dependencies.history.stageSelection();

        this.dispatchTo("before_paste_handlers", selection, ev);
        selection = this.dependencies.selection.getEditableSelection();

        if (!this.delegateTo("paste_overrides", selection, ev.clipboardData)) {
            this.handlePasteUnsupportedHtml(selection, ev.clipboardData) ||
                this.handlePasteOdooEditorHtml(ev.clipboardData) ||
                this.handlePasteHtml(selection, ev.clipboardData) ||
                this.handlePasteText(selection, ev.clipboardData);
        }

        this.dispatchTo("after_paste_handlers", selection);
        this.dependencies.history.addStep();
    }
    /**
     * @param {EditorSelection} selection
     * @param {DataTransfer} clipboardData
     */
    handlePasteUnsupportedHtml(selection, clipboardData) {
        if (!isHtmlContentSupported(selection)) {
            const text = clipboardData.getData("text/plain");
            this.dependencies.dom.insert(text);
            return true;
        }
    }
    /**
     * @param {DataTransfer} clipboardData
     */
    handlePasteOdooEditorHtml(clipboardData) {
        const odooEditorHtml = clipboardData.getData(
            "application/vnd.odoo.odoo-editor",
        );
        const textContent = clipboardData.getData("text/plain");
        if (ONLY_LINK_REGEX.test(textContent)) {
            return false;
        }
        if (odooEditorHtml) {
            const fragment = parseHTML(this.document, odooEditorHtml);
            this.dependencies.sanitize.sanitize(fragment);
            if (this.delegateTo("handle_paste_html_override", fragment)) {
                return true;
            }
            if (fragment.hasChildNodes()) {
                this.dependencies.dom.insert(fragment);
            }
            return true;
        }
    }
    /**
     * @param {EditorSelection} selection
     * @param {DataTransfer} clipboardData
     */
    handlePasteHtml(selection, clipboardData) {
        const files = this.delegateTo("bypass_paste_image_files")
            ? []
            : getImageFiles(clipboardData);
        const clipboardHtml = clipboardData.getData("text/html");
        const textContent = clipboardData.getData("text/plain");
        if (ONLY_LINK_REGEX.test(textContent)) {
            return false;
        }
        const fragment = parseHTML(this.document, clipboardHtml);
        this.dependencies.sanitize.sanitize(fragment);
        if (this.delegateTo("handle_paste_html_override", fragment)) {
            return true;
        }
        if (files.length || clipboardHtml) {
            const clipboardElem = this.prepareClipboardData(clipboardHtml);
            if (files.length && !clipboardElem.querySelector("table")) {
                return this.addImagesFiles(files).then((html) => {
                    this.dependencies.dom.insert(html);
                    this.dependencies.history.addStep();
                });
            } else if (clipboardElem.hasChildNodes()) {
                if (closestElement(selection.anchorNode, "a")) {
                    this.dependencies.dom.insert(clipboardElem.textContent);
                } else {
                    this.dependencies.dom.insert(clipboardElem);
                }
            }
            return true;
        }
    }
    /**
     * @param {EditorSelection} selection
     * @param {DataTransfer} clipboardData
     */
    handlePasteText(selection, clipboardData) {
        const text = clipboardData.getData("text/plain");
        if (this.delegateTo("paste_text_overrides", selection, text)) {
            return;
        } else {
            this.pasteText(text);
        }
    }
    /**
     * @param {string} text
     */
    pasteText(text) {
        const textFragments = text.split(/\r?\n/);
        let selection = this.dependencies.selection.getEditableSelection();
        const preEl = closestElement(selection.anchorNode, "PRE");
        let textIndex = 1;
        for (const textFragment of textFragments) {
            let modifiedTextFragment = textFragment;

            if (!preEl) {
                modifiedTextFragment = textFragment.replace(/( {2,})/g, (match) => {
                    let alternateValue = false;
                    return match.replace(/ /g, () => {
                        alternateValue = !alternateValue;
                        const replaceContent = alternateValue ? "\u00A0" : " ";
                        return replaceContent;
                    });
                });
            }
            this.dependencies.dom.insert(modifiedTextFragment);
            if (textIndex < textFragments.length) {
                selection = this.dependencies.selection.getEditableSelection();
                const block = closestBlock(selection.anchorNode);
                if (
                    this.dependencies.split.isUnsplittable(block) ||
                    closestElement(selection.anchorNode).tagName === "PRE"
                ) {
                    this.dependencies.lineBreak.insertLineBreak();
                } else {
                    const [blockBefore] = this.dependencies.split.splitBlock();
                    if (
                        block &&
                        block.matches(baseContainerGlobalSelector) &&
                        blockBefore &&
                        !blockBefore.matches(getBaseContainerSelector("DIV"))
                    ) {
                        const div =
                            this.dependencies.baseContainer.createBaseContainer("DIV");
                        const cursors = this.dependencies.selection.preserveSelection();
                        blockBefore.before(div);
                        div.replaceChildren(...childNodes(blockBefore));
                        blockBefore.remove();
                        cursors.remapNode(blockBefore, div).restore();
                    }
                }
            }
            textIndex++;
        }
    }

    /**
     * @private
     * @param {string} clipboardData
     * @returns {DocumentFragment}
     */
    prepareClipboardData(clipboardData) {
        const fragment = parseHTML(this.document, clipboardData);
        this.dependencies.sanitize.sanitize(fragment);
        const container = this.document.createElement("fake-container");
        container.append(fragment);

        for (const tableElement of container.querySelectorAll("table")) {
            tableElement.classList.add("table", "table-bordered", "o_table");
        }
        if (this.delegateTo("bypass_paste_image_files")) {
            for (const imgElement of container.querySelectorAll("img")) {
                imgElement.remove();
            }
        }

        const progId = container.querySelector('meta[name="ProgId"]');
        if (progId && progId.content === "Excel.Sheet") {
            const xlStylesheet = container.querySelector("style");
            const xlNodes = container.querySelectorAll("[class*=xl],[class*=font]");
            for (const xlNode of xlNodes) {
                for (const xlClass of xlNode.classList) {
                    const xlStyle = xlStylesheet.textContent
                        .match(`.${xlClass}[^{]*{(?<xlStyle>[^}]*)}`)
                        .groups.xlStyle.replace("background:", "background-color:");
                    xlNode.setAttribute("style", xlNode.style.cssText + ";" + xlStyle);
                }
            }
        }
        const childContent = childNodes(container);
        for (const child of childContent) {
            this.cleanForPaste(child);
        }
        const selection = this.dependencies.selection.getEditableSelection();
        const closestBaseContainer =
            selection.anchorNode &&
            closestElement(selection.anchorNode, baseContainerGlobalSelector);
        wrapInlinesInBlocks(container, {
            baseContainerNodeName:
                closestBaseContainer?.nodeName ||
                this.dependencies.baseContainer.getDefaultNodeName(),
        });
        const result = this.document.createDocumentFragment();
        result.replaceChildren(...childNodes(container));

        const brs = result.querySelectorAll("br");
        for (const br of brs) {
            const block = closestBlock(br);
            if (
                (isParagraphRelatedElement(block) ||
                    this.dependencies.baseContainer.isCandidateForBaseContainer(
                        block,
                    )) &&
                block.nodeName !== "PRE"
            ) {
                const isEmptyLine = block.firstChild.nodeName === "BR";
                const remainingBrContainer = this.dependencies.split.splitAroundUntil(
                    br,
                    block,
                );
                if (!isEmptyLine) {
                    remainingBrContainer.remove();
                }
            }
        }
        return result;
    }
    /**
     * @param {Node} node
     */
    cleanForPaste(node) {
        if (
            !this.isWhitelisted(node) ||
            this.isBlacklisted(node) ||
            (node.id && node.id.startsWith("docs-internal-guid"))
        ) {
            if (!node.matches || node.matches(CLIPBOARD_BLACKLISTS.remove.join(","))) {
                node.remove();
            } else {
                let childrenNodes;
                if (node.nodeName === "DIV") {
                    if (!node.hasChildNodes()) {
                        node.remove();
                        return;
                    } else if (
                        this.dependencies.baseContainer.isCandidateForBaseContainer(
                            node,
                        )
                    ) {
                        const whiteSpace = node.style?.whiteSpace;
                        if (whiteSpace && !["normal", "nowrap"].includes(whiteSpace)) {
                            node.innerHTML = node.innerHTML.replace(/\n/g, "<br>");
                        }
                        const baseContainer =
                            this.dependencies.baseContainer.createBaseContainer();
                        const dir = node.getAttribute("dir");
                        if (dir) {
                            baseContainer.setAttribute("dir", dir);
                        }
                        baseContainer.append(...node.childNodes);

                        node.replaceWith(baseContainer);
                        childrenNodes = childNodes(baseContainer);
                    } else {
                        childrenNodes = unwrapContents(node);
                    }
                } else {
                    childrenNodes = unwrapContents(node);
                }
                for (const child of childrenNodes) {
                    this.cleanForPaste(child);
                }
            }
        } else if (node.nodeType !== Node.TEXT_NODE) {
            if (node.nodeName === "THEAD") {
                const tbody = node.nextElementSibling;
                if (tbody) {
                    tbody.prepend(...node.children);
                    node.remove();
                    node = tbody;
                } else {
                    node = this.dependencies.dom.setTagName(node, "TBODY");
                }
            } else if (["TD", "TH"].includes(node.nodeName)) {
                if (isEmptyBlock(node)) {
                    const baseContainer =
                        this.dependencies.baseContainer.createBaseContainer();
                    fillEmpty(baseContainer);
                    node.replaceChildren(baseContainer);
                }

                if (node.hasAttribute("bgcolor") && !node.style["background-color"]) {
                    node.style["background-color"] = node.getAttribute("bgcolor");
                }
            } else if (node.nodeName === "FONT") {
                if (node.hasAttribute("color") && !node.style["color"]) {
                    node.style["color"] = node.getAttribute("color");
                }
                if (node.hasAttribute("size") && !node.style["font-size"]) {
                    node.style["font-size"] = +node.getAttribute("size") + 10 + "pt";
                }
            } else if (
                ["S", "U"].includes(node.nodeName) &&
                childNodes(node).length === 1 &&
                node.firstChild.nodeName === "FONT"
            ) {
                const fontNode = node.firstChild;
                node.before(fontNode);
                node.replaceChildren(...childNodes(fontNode));
                fontNode.appendChild(node);
            } else if (
                node.nodeName === "IMG" &&
                node.getAttribute("aria-roledescription") === "checkbox"
            ) {
                const checklist = node.closest("ul");
                const closestLi = node.closest("li");
                if (checklist) {
                    checklist.classList.add("o_checklist");
                    if (node.getAttribute("alt") === "checked") {
                        closestLi.classList.add("o_checked");
                    }
                    node.remove();
                    node = checklist;
                }
            }
            for (const attribute of [...node.attributes]) {
                if (
                    CLIPBOARD_WHITELISTS.styledTags.includes(node.nodeName) &&
                    attribute.name === "style"
                ) {
                    node.removeAttribute(attribute.name);
                    if (["SPAN", "FONT"].includes(node.tagName)) {
                        for (const unwrappedNode of unwrapContents(node)) {
                            this.cleanForPaste(unwrappedNode);
                        }
                    }
                } else if (!this.isWhitelisted(attribute)) {
                    node.removeAttribute(attribute.name);
                }
            }
            for (const klass of [...node.classList]) {
                if (!this.isWhitelisted(klass)) {
                    node.classList.remove(klass);
                }
            }
            for (const child of childNodes(node)) {
                this.cleanForPaste(child);
            }
        }
    }
    /**
     * @private
     * @param {Attr | string | Node} item
     * @returns {boolean}
     */
    isWhitelisted(item) {
        if (item.nodeType === Node.ATTRIBUTE_NODE) {
            return CLIPBOARD_WHITELISTS.attributes.includes(item.name);
        } else if (typeof item === "string") {
            return CLIPBOARD_WHITELISTS.classes.some((okClass) =>
                okClass instanceof RegExp ? okClass.test(item) : okClass === item,
            );
        } else {
            return (
                isTextNode(item) || item.matches?.(CLIPBOARD_WHITELISTS.nodes.join(","))
            );
        }
    }
    /**
     * @private
     * @param {Node} node
     * @returns {boolean}
     */
    isBlacklisted(node) {
        return (
            !isTextNode(node) &&
            node.matches([].concat(...Object.values(CLIPBOARD_BLACKLISTS)).join(","))
        );
    }

    /**
     * @param {DragEvent} ev
     */
    onDragStart(ev) {
        const selection = this.dependencies.selection.getEditableSelection();
        this.dispatchTo("before_drag_handlers", selection);
        this.setSelectionTransferData(ev, "dataTransfer");
    }
    /**
     * @param {DragEvent} ev
     */
    async onDrop(ev) {
        ev.preventDefault();
        const selection = this.dependencies.selection.getEditableSelection();
        if (!isHtmlContentSupported(selection)) {
            return;
        }
        const nodeToSplit =
            selection.direction === DIRECTIONS.RIGHT
                ? selection.focusNode
                : selection.anchorNode;
        const offsetToSplit =
            selection.direction === DIRECTIONS.RIGHT
                ? selection.focusOffset
                : selection.anchorOffset;
        if (nodeToSplit.nodeType === Node.TEXT_NODE && !selection.isCollapsed) {
            const selectionToRestore = this.dependencies.selection.preserveSelection();
            splitTextNode(nodeToSplit, offsetToSplit, DIRECTIONS.LEFT);
            selectionToRestore.restore();
        }

        const dataTransfer = (ev.originalEvent || ev).dataTransfer;
        const odooEditorHtml = ev.dataTransfer.getData(
            "application/vnd.odoo.odoo-editor",
        );
        const fileTransferItems = !odooEditorHtml && getImageFiles(dataTransfer);
        const htmlTransferItem = [...dataTransfer.items].find(
            (item) => item.type === "text/html",
        );
        if (fileTransferItems.length || htmlTransferItem || odooEditorHtml) {
            const deleteAndSetSelection = (offsetNode, offset) => {
                if (offsetNode.nodeType === Node.ELEMENT_NODE && offset > 1) {
                    const initialLength = offsetNode.childNodes.length;
                    this.dependencies.delete.deleteSelection();
                    const removedCount = initialLength - offsetNode.childNodes.length;
                    offset -= removedCount;
                } else {
                    this.dependencies.delete.deleteSelection();
                }

                this.dependencies.selection.setSelection({
                    anchorNode: offsetNode,
                    anchorOffset: offset,
                });
            };

            if (this.document.caretPositionFromPoint) {
                const range = this.document.caretPositionFromPoint(
                    ev.clientX,
                    ev.clientY,
                );
                deleteAndSetSelection(range.offsetNode, range.offset);
            } else if (this.document.caretRangeFromPoint) {
                const range = this.document.caretRangeFromPoint(ev.clientX, ev.clientY);
                deleteAndSetSelection(range.startContainer, range.startOffset);
            }
        }
        if (odooEditorHtml) {
            const fragment = parseHTML(this.document, odooEditorHtml);
            this.dependencies.sanitize.sanitize(fragment);
            if (fragment.hasChildNodes()) {
                this.dependencies.dom.insert(fragment);
                this.dependencies.history.addStep();
            }
        } else if (fileTransferItems.length) {
            const html = await this.addImagesFiles(fileTransferItems);
            this.dependencies.dom.insert(html);
            this.dependencies.history.addStep();
        } else if (htmlTransferItem) {
            htmlTransferItem.getAsString((pastedText) => {
                this.dependencies.dom.insert(this.prepareClipboardData(pastedText));
                this.dependencies.history.addStep();
            });
        }
    }
    /**
     * @param {File[]} imageFiles
     */
    async addImagesFiles(imageFiles) {
        const promises = [];
        for (const imageFile of imageFiles) {
            const imageNode = this.document.createElement("img");
            imageNode.classList.add("img-fluid");
            this.dispatchTo("added_image_handlers", imageNode);
            imageNode.dataset.fileName = imageFile.name;
            promises.push(
                getImageUrl(imageFile).then((url) => {
                    imageNode.src = url;
                    return imageNode;
                }),
            );
        }
        const nodes = await Promise.all(promises);
        const fragment = this.document.createDocumentFragment();
        fragment.append(...nodes);
        return fragment;
    }
}

/**
 * @param {DataTransfer} dataTransfer
 */
function getImageFiles(dataTransfer) {
    return [...dataTransfer.items]
        .filter((item) => item.kind === "file" && item.type.includes("image/"))
        .map((item) => item.getAsFile());
}
/**
 * @param {File} file
 */
function getImageUrl(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();

        reader.readAsDataURL(file);
        reader.onloadend = (e) => {
            if (reader.error) {
                return reject(reader.error);
            }
            resolve(e.target.result);
        };
    });
}
