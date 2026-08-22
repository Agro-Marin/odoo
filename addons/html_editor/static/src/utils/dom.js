/** @odoo-module native */
import {
    baseContainerGlobalSelector,
    createBaseContainer,
} from "@html_editor/utils/base_container";

import { isEmptyBlock, isPhrasingContent } from "../utils/dom_info.js";
import { closestBlock, isBlock } from "./blocks.js";
import {
    isElement,
    isEmptyTextNode,
    isParagraphRelatedElement,
    isShrunkBlock,
    isTextNode,
    isVisible,
    nextLeaf,
    previousLeaf,
} from "./dom_info.js";
import { childNodes, descendants } from "./dom_traversal.js";
import { childNodeIndex, DIRECTIONS, nodeSize } from "./position.js";
import { callbacksForCursorUpdate } from "./selection.js";

/** @typedef {import("@html_editor/core/selection_plugin").Cursors} Cursors */

/**
 * @param {Node} node
 */
export function makeContentsInline(node) {
    const document = node.ownerDocument;
    let currentNode = node.firstChild;
    while (currentNode) {
        if (isBlock(currentNode)) {
            if (currentNode.previousSibling && isParagraphRelatedElement(currentNode)) {
                currentNode.before(document.createElement("br"));
            }
            currentNode = unwrapContents(currentNode)[0];
        } else {
            currentNode = currentNode.nextSibling;
        }
    }
}

/**
 * @param {HTMLElement} element
 * @param {Object} [options]
 * @param {string} [options.baseContainerNodeName="P"]
 * @param {Cursors} [options.cursors]
 */
export function wrapInlinesInBlocks(
    element,
    { baseContainerNodeName = "P", cursors = { update: () => {} } } = {},
) {
    const wrapInBlock = (node, cursors) => {
        const block = isPhrasingContent(node)
            ? createBaseContainer(baseContainerNodeName, node.ownerDocument)
            : node.ownerDocument.createElement("DIV");
        cursors.update(callbacksForCursorUpdate.append(block, node));
        cursors.update(callbacksForCursorUpdate.before(node, block));
        if (node.nextSibling) {
            const sibling = node.nextSibling;
            node.remove();
            sibling.before(block);
        } else {
            const parent = node.parentElement;
            node.remove();
            parent.append(block);
        }
        block.append(node);
        return block;
    };
    const appendToCurrentBlock = (currentBlock, node, cursors) => {
        if (
            currentBlock.matches(baseContainerGlobalSelector) &&
            !isPhrasingContent(node)
        ) {
            const block = currentBlock.ownerDocument.createElement("DIV");
            cursors.update(callbacksForCursorUpdate.before(currentBlock, block));
            currentBlock.before(block);
            for (const child of childNodes(currentBlock)) {
                cursors.update(callbacksForCursorUpdate.append(block, child));
                block.append(child);
            }
            cursors.update(callbacksForCursorUpdate.remove(currentBlock));
            currentBlock.remove();
            currentBlock = block;
        }
        cursors.update(callbacksForCursorUpdate.append(currentBlock, node));
        currentBlock.append(node);
        return currentBlock;
    };
    const removeNode = (node, cursors) => {
        cursors.update(callbacksForCursorUpdate.remove(node));
        node.remove();
    };

    const children = childNodes(element);
    const visibleNodes = new Set(children.filter(isVisible));

    let currentBlock;
    let shouldBreakLine = true;
    for (const node of children) {
        if (isBlock(node)) {
            shouldBreakLine = true;
        } else if (!visibleNodes.has(node)) {
            removeNode(node, cursors);
        } else if (node.nodeName === "BR") {
            if (shouldBreakLine) {
                wrapInBlock(node, cursors);
            } else {
                removeNode(node, cursors);
                shouldBreakLine = true;
            }
        } else if (shouldBreakLine) {
            currentBlock = wrapInBlock(node, cursors);
            shouldBreakLine = false;
        } else {
            currentBlock = appendToCurrentBlock(currentBlock, node, cursors);
        }
    }
}

export function unwrapContents(node) {
    const contents = childNodes(node);
    for (const child of contents) {
        node.parentNode.insertBefore(child, node);
    }
    node.parentNode.removeChild(node);
    return contents;
}

/**
 * @param {Element} element
 * @param {...string} classNames
 */
export function removeClass(element, ...classNames) {
    const classNamesSet = new Set(classNames);
    if ([...element.classList].every((className) => classNamesSet.has(className))) {
        element.removeAttribute("class");
    } else {
        element.classList.remove(...classNames);
    }
}

export function removeStyle(element, ...styleProperties) {
    const propsToRemoveSet = new Set(styleProperties);
    if ([...element.style].every((prop) => propsToRemoveSet.has(prop))) {
        element.removeAttribute("style");
    } else {
        styleProperties.forEach((prop) => element.style.removeProperty(prop));
    }
}

/**
 * @param {HTMLElement} el
 * @returns {Object}
 */
export function fillEmpty(el) {
    const document = el.ownerDocument;
    if (
        !isVisible(el) &&
        !el.hasAttribute("data-oe-zws-empty-inline") &&
        !isBlock(el)
    ) {
        const zws = document.createTextNode("\u200B");
        el.appendChild(zws);
        el.setAttribute("data-oe-zws-empty-inline", "");
        const previousSibling = el.previousSibling;
        if (previousSibling && previousSibling.nodeName === "BR") {
            previousSibling.remove();
        }
        return { zws };
    } else {
        return fillShrunkPhrasingParent(el);
    }
}

/**
 * @param {HTMLElement} el
 * @returns {Object}
 */
export function fillShrunkPhrasingParent(el) {
    const document = el.ownerDocument;
    const fillers = {};
    const blockEl = closestBlock(el);
    if (isShrunkBlock(blockEl)) {
        const br = document.createElement("br");
        blockEl.appendChild(br);
        fillers.br = br;
    }
    return fillers;
}

/**
 * @param {HTMLElement} el
 * @param {Array} predicates
 * @returns {HTMLElement|undefined}
 */
export function cleanTrailingBR(el, predicates = []) {
    const candidate = el?.lastChild;
    if (
        candidate?.nodeName === "BR" &&
        candidate.previousSibling?.nodeName !== "BR" &&
        !isEmptyBlock(el) &&
        !predicates.some((predicate) => predicate(candidate))
    ) {
        candidate.remove();
        return candidate;
    }
}

/**
 * @param {Element} element
 * @param {string} className
 * @param {boolean} [force]
 */
export function toggleClass(element, className, force) {
    element.classList.toggle(className, force);
    if (!element.className) {
        element.removeAttribute("class");
    }
}

export function cleanEmptyAncestors(node, cursors, exclude = () => false) {
    let currentNode = node;
    while (currentNode && !nodeSize(currentNode) && !exclude(currentNode)) {
        cursors?.update(callbacksForCursorUpdate.remove(currentNode));
        const parent = currentNode.parentNode;
        currentNode.remove();
        currentNode = parent;
    }
}

/**
 * @param {Node} node
 * @param {String} char
 * @param {Cursors} [cursors]
 */
export function cleanTextNode(node, char, cursors) {
    const removedIndexes = [];
    node.textContent = node.textContent.replaceAll(char, (_, offset) => {
        removedIndexes.push(offset);
        return "";
    });
    if (isEmptyTextNode(node)) {
        cursors?.update(callbacksForCursorUpdate.remove(node));
        node.remove();
    } else {
        cursors?.update((cursor) => {
            if (cursor.node === node) {
                cursor.offset -= removedIndexes.filter(
                    (index) => cursor.offset > index,
                ).length;
            }
        });
    }
}

/**
 * @param {HTMLElement} root
 * @param {Cursors} [cursors]
 */
export function removeEmptyTextNodes(root, cursors) {
    for (const node of childNodes(root).filter((n) => isEmptyTextNode(n))) {
        cursors?.update(callbacksForCursorUpdate.remove(node));
        node.remove();
    }
}

/**
 * @param {Text} textNode
 * @param {number} offset
 * @param {boolean} originalNodeSide
 * @returns {number}
 */
export function splitTextNode(textNode, offset, originalNodeSide = DIRECTIONS.RIGHT) {
    const document = textNode.ownerDocument;
    let parentOffset = childNodeIndex(textNode);

    if (offset > 0) {
        parentOffset++;

        if (offset < textNode.length) {
            const left = textNode.nodeValue.substring(0, offset);
            const right = textNode.nodeValue.substring(offset);
            if (originalNodeSide === DIRECTIONS.LEFT) {
                const newTextNode = document.createTextNode(right);
                textNode.after(newTextNode);
                textNode.nodeValue = left;
            } else {
                const newTextNode = document.createTextNode(left);
                textNode.before(newTextNode);
                textNode.nodeValue = right;
            }
        }
    }
    return parentOffset;
}

/**
 * @param {Element} el
 * @param {import("@html_editor/core/selection_plugin").Cursors} [cursors]
 */
export function removeInvisibleWhitespace(el, cursors) {
    const whitespaceRegex = /[^\S\u00A0\uFEFF]/;
    const [countLeadingWhitespace, countTrailingWhitespace] = [
        new RegExp(`^${whitespaceRegex.source}+`),
        new RegExp(`${whitespaceRegex.source}+$`),
    ].map((regex) => (node) => node?.textContent.match(regex)?.[0]?.length || 0);
    const isInlineElement = (node) =>
        node?.nodeType === Node.ELEMENT_NODE && !isBlock(node);
    const textChildren = descendants(el).filter(
        (child) => child.nodeType === Node.TEXT_NODE,
    );
    let removedTrailingSpaceBefore = false;
    let index = 0;
    for (const child of textChildren) {
        let leadingWhitespace = countLeadingWhitespace(child);
        let trailingWhitespace = countTrailingWhitespace(child);
        const previous = previousLeaf(child, el);
        if (
            leadingWhitespace &&
            previous &&
            (isInlineElement(child.previousSibling) || removedTrailingSpaceBefore)
        ) {
            leadingWhitespace -= 1;
        } else if (
            trailingWhitespace &&
            index !== textChildren.length - 1 &&
            isInlineElement(child.nextSibling) &&
            !countTrailingWhitespace(nextLeaf(child, el))
        ) {
            trailingWhitespace -= 1;
        }
        removedTrailingSpaceBefore = !!trailingWhitespace;
        cursors?.shiftOffset(child, -leadingWhitespace);
        child.textContent = child.textContent
            .substring(
                leadingWhitespace,
                child.textContent.length - trailingWhitespace || leadingWhitespace,
            )
            .replace(new RegExp(`^${whitespaceRegex.source}+`), " ")
            .replace(new RegExp(`${whitespaceRegex.source}+$`), " ");
        if (!child.textContent) {
            child.remove();
        }
        index += 1;
    }
}

/**
 * @param {HTMLElement} node
 * @param {Cursors} cursor
 */
export function mergeAdjacentTextNodes(node, cursor) {
    let child = node.firstChild;
    while (child) {
        if (isElement(child)) {
            mergeAdjacentTextNodes(child, cursor);
        }

        const next = child.nextSibling;
        if (isTextNode(child) && next && isTextNode(next)) {
            if (cursor.anchor.node === next) {
                cursor.anchor.node = child;
                cursor.anchor.offset = child.textContent.length + cursor.anchor.offset;
            }
            if (cursor.focus.node === next) {
                cursor.focus.node = child;
                cursor.focus.offset = child.textContent.length + cursor.focus.offset;
            }
            child.textContent += next.textContent;
            next.remove();
        } else {
            child = next;
        }
    }
}
