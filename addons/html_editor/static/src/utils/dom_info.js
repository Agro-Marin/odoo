/** @odoo-module native */
import { baseContainerGlobalSelector } from "./base_container.js";
import { closestBlock, isBlock } from "./blocks.js";
import { childNodes, closestElement, firstLeaf, lastLeaf } from "./dom_traversal.js";
import { childNodeIndex, DIRECTIONS, nodeSize } from "./position.js";

export function isEmpty(el) {
    if (isProtecting(el) || isProtected(el)) {
        return false;
    }
    const content = el.innerHTML.trim();
    if (content === "" || content === "<br>") {
        return true;
    }
    return false;
}

export function isEmptyTextNode(node) {
    if (node.nodeType !== Node.TEXT_NODE) {
        return false;
    }
    if (!node.textContent) {
        return true;
    }
    const trimmedContent = node.textContent.trim();
    if (!trimmedContent) {
        if (node.textContent.includes("\n")) {
            return true;
        }
        if (node.textContent) {
            return false;
        }
    }
    return !trimmedContent;
}

/**
 * @param {Node} node
 * @returns {boolean}
 */
export function isBold(node) {
    const fontWeight = +getComputedStyle(closestElement(node)).fontWeight;
    const referenceElement = closestElement(
        node,
        (el) => isBlock(el) || +getComputedStyle(el).fontWeight !== fontWeight,
    );
    return (
        fontWeight > 500 || fontWeight > +getComputedStyle(referenceElement).fontWeight
    );
}

/**
 * @param {Node} node
 * @returns {boolean}
 */
export function isItalic(node) {
    return getComputedStyle(closestElement(node)).fontStyle === "italic";
}

/**
 * @param {Node} node
 * @returns {boolean}
 */
export function isUnderline(node) {
    let parent = closestElement(node);
    while (parent) {
        if (getComputedStyle(parent).textDecorationLine.includes("underline")) {
            return true;
        }
        parent = parent.parentElement;
    }
    return false;
}

/**
 * @param {Node} node
 * @returns {boolean}
 */
export function isStrikeThrough(node) {
    let parent = closestElement(node);
    while (parent) {
        if (
            !parent.classList.contains("o_checked") &&
            getComputedStyle(parent).textDecorationLine.includes("line-through")
        ) {
            return true;
        }
        parent = parent.parentElement;
    }
    return false;
}

/**
 * @param {Node} node
 * @param {Object} props
 * @param {String} props.size
 * @returns {boolean}
 */
export function isFontSize(node, props) {
    const element = closestElement(node);
    return getComputedStyle(element)["font-size"] === props.size;
}

/**
 * @param {Node} node
 * @param {Object} props
 * @param {String} props.className
 * @returns {boolean}
 */
export function hasClass(node, props) {
    const element = closestElement(node);
    return element.classList.contains(props.className);
}

/**
 * @param {Node} node
 * @param {Element} editable
 * @returns {boolean}
 */
export function isDirectionSwitched(node, editable) {
    const defaultDirection = editable.getAttribute("dir") || "ltr";
    return getComputedStyle(closestElement(node)).direction !== defaultDirection;
}

export function isRow(node) {
    return ["TH", "TD"].includes(node.tagName);
}

export function isZWS(node) {
    return node && node.textContent === "\u200B";
}

/**
 * @param {Node} node
 * @returns {boolean}
 */
export function isInPre(node) {
    const element = node.nodeType === Node.TEXT_NODE ? node.parentElement : node;
    return (
        !!element &&
        (!!element.closest("pre") ||
            getComputedStyle(element).getPropertyValue("white-space") === "pre")
    );
}

export const ZERO_WIDTH_CHARS = ["\u200b", "\ufeff"];

export const whitespace = `[^\\S\\u00A0\\u0009\\ufeff]`;
const whitespaceRegex = new RegExp(`^${whitespace}*$`);
export function isWhitespace(value) {
    const str = typeof value === "string" ? value : value.nodeValue;
    return whitespaceRegex.test(str);
}

// eslint-disable-next-line no-control-regex
const visibleCharRegex = /[^\s\u200b]|[\u00A0\u0009]$/;
export function isVisibleTextNode(testedNode) {
    if (!testedNode || !testedNode.length || testedNode.nodeType !== Node.TEXT_NODE) {
        return false;
    }
    if (isProtected(testedNode)) {
        return true;
    }
    if (
        visibleCharRegex.test(testedNode.textContent) ||
        (isInPre(testedNode) && isWhitespace(testedNode))
    ) {
        return true;
    }
    if (ZERO_WIDTH_CHARS.includes(testedNode.textContent)) {
        return false;
    }
    let preceding;
    let following;
    let foundTestedNode;
    const currentNodeParentBlock = closestBlock(testedNode);
    if (!currentNodeParentBlock) {
        return false;
    }
    const nodeIterator = document.createNodeIterator(currentNodeParentBlock);
    for (let node = nodeIterator.nextNode(); node; node = nodeIterator.nextNode()) {
        if (node.nodeType === Node.TEXT_NODE) {
            if (foundTestedNode) {
                following = node;
                break;
            } else if (testedNode === node) {
                foundTestedNode = true;
            } else {
                preceding = node;
            }
        } else if (isBlock(node)) {
            if (foundTestedNode) {
                break;
            } else {
                preceding = null;
            }
        } else if (foundTestedNode && !isWhitespace(node)) {
            following = node;
            break;
        }
    }
    while (following && !visibleCharRegex.test(following.textContent)) {
        following = following.nextSibling;
    }
    if (
        !(preceding && following) ||
        currentNodeParentBlock !== closestBlock(preceding) ||
        currentNodeParentBlock !== closestBlock(following)
    ) {
        return false;
    }
    return visibleCharRegex.test(preceding.textContent);
}

/**
 * @param {Node} node
 * @returns {boolean}
 */
const selfClosingElementTags = ["BR", "IMG", "INPUT", "T", "HR"];
export function isSelfClosingElement(node) {
    return node && selfClosingElementTags.includes(node.nodeName);
}

/**
 * @param {Node} node
 * @returns {boolean}
 */
export function isVisible(node) {
    return (
        !!node &&
        ((node.nodeType === Node.TEXT_NODE && isVisibleTextNode(node)) ||
            isSelfClosingElement(node) ||
            isMediaElement(node) ||
            hasVisibleContent(node) ||
            isProtecting(node) ||
            isEmbeddedComponent(node) ||
            (node.nodeName === "TD" && !!closestElement(node, "table.o_table")))
    );
}
export function hasVisibleContent(node) {
    return (node ? childNodes(node) : []).some((n) => isVisible(n));
}

export function isButton(node) {
    if (!node || node.nodeType !== Node.ELEMENT_NODE) {
        return false;
    }
    return node.nodeName === "BUTTON" || node.classList.contains("btn");
}

export function isZwnbsp(node) {
    return node?.nodeType === Node.TEXT_NODE && node.textContent === "\ufeff";
}

export function isTangible(node) {
    return isVisible(node) || isZwnbsp(node) || hasTangibleContent(node);
}

export function hasTangibleContent(node) {
    return (node ? childNodes(node) : []).some((n) => isTangible(n));
}

export const isNotEditableNode = (node) =>
    node.getAttribute &&
    node.getAttribute("contenteditable") &&
    node.getAttribute("contenteditable").toLowerCase() === "false";

const iconTags = ["I", "SPAN"];
export const iconClasses = [
    "fa",
    "fab",
    "fad",
    "far",
    "oi",
    "fa-solid",
    "fa-regular",
    "fa-brands",
];

export const ICON_SELECTOR = iconTags
    .map((tag) => iconClasses.map((cls) => `${tag}.${cls}`).join(", "))
    .join(", ");

export const MEDIA_SELECTOR = `${ICON_SELECTOR}, .media_iframe_video, .o_file_box`;

export const EDITABLE_MEDIA_CLASS = "o_editable_media";

/**
 * @param {?Node} [node]
 * @returns {boolean}
 */
export function isIconElement(node) {
    return !!(
        node &&
        iconTags.includes(node.nodeName) &&
        iconClasses.some((cls) => node.classList.contains(cls))
    );
}
export function isMediaElement(node) {
    return (
        isIconElement(node) ||
        (node.classList &&
            (node.classList.contains("o_file_box") ||
                node.classList.contains("media_iframe_video"))) ||
        node.nodeName === "CANVAS"
    );
}

/**
 * @param {HTMLElement} mediaContainerEl
 * @param {boolean} [requiresSingleMedia=false]
 * @returns {boolean}
 */
export function hasMediaOnly(mediaContainerEl, requiresSingleMedia = false) {
    const nonEmptyContent = [...mediaContainerEl.childNodes].filter(
        (node) =>
            node.tagName !== "BR" &&
            (node.nodeType !== Node.TEXT_NODE ||
                node.textContent.replaceAll(/\s+/g, "")),
    );
    if (requiresSingleMedia && nonEmptyContent.length !== 1) {
        return false;
    }
    return nonEmptyContent.every((el) => {
        if (isMediaElement(el) || el.tagName === "IMG") {
            return true;
        }
        if (el.tagName === "A") {
            return hasMediaOnly(el, requiresSingleMedia);
        }
    });
}

const phrasingTagNames = new Set([
    "ABBR",
    "AUDIO",
    "B",
    "BDI",
    "BDO",
    "BR",
    "BUTTON",
    "CANVAS",
    "CITE",
    "CODE",
    "DATA",
    "DATALIST",
    "DFN",
    "EM",
    "EMBED",
    "I",
    "IFRAME",
    "IMG",
    "INPUT",
    "KBD",
    "LABEL",
    "MARK",
    "MATH",
    "METER",
    "NOSCRIPT",
    "OBJECT",
    "OUTPUT",
    "PICTURE",
    "PROGRESS",
    "Q",
    "RUBY",
    "S",
    "SAMP",
    "SCRIPT",
    "SELECT",
    "SLOT",
    "SMALL",
    "SPAN",
    "STRONG",
    "SUB",
    "SUP",
    "SVG",
    "TEMPLATE",
    "TEXTAREA",
    "TIME",
    "U",
    "VAR",
    "VIDEO",
    "WBR",
    "FONT",
    "A",
    "AREA",
    "DEL",
    "INS",
    "LINK",
    "MAP",
    "META",
]);

export function isPhrasingContent(node) {
    if (
        node &&
        (node.nodeType === Node.TEXT_NODE ||
            (node.nodeType === Node.ELEMENT_NODE && phrasingTagNames.has(node.tagName)))
    ) {
        return true;
    }
    return false;
}

export function containsAnyInline(element) {
    if (!element) {
        return false;
    }
    let child = element.firstChild;
    while (child) {
        if (
            (!isBlock(child) && child.nodeType === Node.ELEMENT_NODE) ||
            (child.nodeType === Node.TEXT_NODE && child.textContent.trim() !== "")
        ) {
            return true;
        }
        child = child.nextSibling;
    }
    return false;
}

export function containsAnyNonPhrasingContent(element) {
    if (!element) {
        return false;
    }
    let child = element.firstChild;
    while (child) {
        if (!isPhrasingContent(child)) {
            return true;
        }
        child = child.nextSibling;
    }
    return false;
}

export function isEmbeddedComponent(node) {
    return node.nodeType === Node.ELEMENT_NODE && node.matches("[data-embedded]");
}

/**
 * @param {Node} node
 * @returns {boolean}
 */
export function isProtected(node) {
    if (!node) {
        return false;
    }
    const candidate = node.parentElement
        ? closestElement(node.parentElement, "[data-oe-protected]")
        : null;
    if (!candidate || candidate.dataset.oeProtected === "false") {
        return false;
    }
    return true;
}

/**
 * @param {Node} node
 * @returns {boolean}
 */
export function isProtecting(node) {
    if (!node) {
        return false;
    }
    return (
        node.nodeType === Node.ELEMENT_NODE &&
        node.dataset.oeProtected !== "false" &&
        node.dataset.oeProtected !== undefined
    );
}

export function isUnprotecting(node) {
    if (!node) {
        return false;
    }
    return node.nodeType === Node.ELEMENT_NODE && node.dataset.oeProtected === "false";
}

export const paragraphRelatedElements = [
    "P",
    "H1",
    "H2",
    "H3",
    "H4",
    "H5",
    "H6",
    "PRE",
];

/**
 * @param {Node} node
 * @returns {boolean}
 */
export function allowsParagraphRelatedElements(node) {
    return !isParagraphRelatedElement(node) && isBlock(node);
}

export const phrasingContent = new Set(["#text", ...phrasingTagNames]);
const flowContent = new Set([
    ...phrasingContent,
    ...paragraphRelatedElements,
    "DIV",
    "HR",
]);
export const listItem = new Set(["LI"]);
const listContainers = new Set(["UL", "OL"]);

const allowedContent = {
    BLOCKQUOTE: flowContent,
    DIV: flowContent,
    H1: phrasingContent,
    H2: phrasingContent,
    H3: phrasingContent,
    H4: phrasingContent,
    H5: phrasingContent,
    H6: phrasingContent,
    HR: new Set(),
    LI: flowContent,
    OL: listItem,
    UL: listItem,
    P: phrasingContent,
    PRE: phrasingContent,
    TD: flowContent,
    TR: new Set(["TD"]),
};

export function isParagraphRelatedElement(node) {
    if (!node) {
        return false;
    }
    return (
        paragraphRelatedElements.includes(node.nodeName) ||
        (node.nodeType === Node.ELEMENT_NODE &&
            node.matches(baseContainerGlobalSelector))
    );
}

export const paragraphRelatedElementsSelector = [
    ...paragraphRelatedElements,
    baseContainerGlobalSelector,
].join(",");

export function isListItemElement(node) {
    return [...listItem].includes(node.nodeName);
}

export const listItemElementSelector = [...listItem].join(",");

export function isListElement(node) {
    return [...listContainers].includes(node.nodeName);
}

export const listElementSelector = [...listContainers].join(",");

export function isTableCell(node) {
    return ["TH", "TD"].includes(node.nodeName);
}

/**
 * @param {Element} parentBlock
 * @param {Node[]} nodes
 * @returns {boolean}
 */
export function isAllowedContent(parentBlock, nodes) {
    let allowedContentSet = allowedContent[parentBlock.nodeName];
    if (!allowedContentSet) {
        return true;
    }
    if (parentBlock.matches(baseContainerGlobalSelector)) {
        allowedContentSet = phrasingContent;
    }
    return nodes.every((node) => allowedContentSet.has(node.nodeName));
}

/**
 * @param {HTMLElement} blockEl
 * @returns {boolean}
 */
export function isEmptyBlock(blockEl) {
    if (!blockEl || blockEl.nodeType !== Node.ELEMENT_NODE) {
        return false;
    }
    if (visibleCharRegex.test(blockEl.textContent)) {
        return false;
    }
    if (blockEl.querySelectorAll("br").length >= 2) {
        return false;
    }
    if (isProtecting(blockEl) || isProtected(blockEl)) {
        return false;
    }
    const nodes = blockEl.querySelectorAll("*");
    for (const node of nodes) {
        if (
            node.nodeName !== "BR" &&
            (isSelfClosingElement(node) ||
                isMediaElement(node) ||
                isProtecting(node) ||
                isButton(node))
        ) {
            return false;
        }
    }
    return isBlock(blockEl);
}
/**
 * @param {HTMLElement} blockEl
 * @returns {boolean}
 */
export function isShrunkBlock(blockEl) {
    return (
        isElement(blockEl) &&
        !blockEl.querySelector("br") &&
        !isSelfClosingElement(blockEl) &&
        isEmptyBlock(blockEl)
    );
}

export function isEditorTab(node) {
    return node && node.nodeName === "SPAN" && node.classList.contains("oe-tabs");
}

export function getDeepestPosition(node, offset) {
    let direction = DIRECTIONS.RIGHT;
    let next = node;
    while (next) {
        if (isTangible(next) || (isZWS(next) && isContentEditable(next))) {
            if (next !== node) {
                [node, offset] = [next, direction ? 0 : nodeSize(next)];
            }
            const childrenNodes = childNodes(node);
            direction = offset < childrenNodes.length;
            next = childrenNodes[direction ? offset : offset - 1];
        } else if (
            direction &&
            next.nextSibling &&
            closestBlock(node).contains(next.nextSibling)
        ) {
            next = next.nextSibling;
        } else {
            direction = DIRECTIONS.LEFT;
            next =
                closestBlock(node).contains(next.previousSibling) &&
                next.previousSibling;
        }
        next = !isSelfClosingElement(next) && next;
    }
    return [node, offset];
}

/**
 * @param {Node} node
 * @param {number} offset
 * @returns {[Node, number]}
 */
export function getDeepestEditablePosition(node, offset) {
    const [deepNode, deepOffset] = getDeepestPosition(node, offset);

    if (isContentEditable(deepNode)) {
        return [deepNode, deepOffset];
    }

    const nodeLevelAncestor =
        isTextNode(deepNode) && deepNode.parentElement === node
            ? deepNode
            : closestElement(deepNode, (el) => el.parentElement === node);

    const closestNonEditable = closestElement(
        deepNode,
        (el) => !isContentEditable(el) && isContentEditable(el.parentElement),
    );

    const nodeLevelAncestorIndex = childNodeIndex(nodeLevelAncestor);
    const closestNonEditableIndex = childNodeIndex(closestNonEditable);

    const deepEditableNode = closestNonEditable.parentElement;
    const deepEditableOffset =
        nodeLevelAncestorIndex < offset
            ? closestNonEditableIndex + 1
            : closestNonEditableIndex;

    if (deepEditableOffset === closestNonEditableIndex) {
        const previousSiblingOfNonEditable = closestNonEditable.previousSibling;
        if (previousSiblingOfNonEditable) {
            if (isTextNode(previousSiblingOfNonEditable)) {
                return [
                    previousSiblingOfNonEditable,
                    nodeSize(previousSiblingOfNonEditable),
                ];
            } else if (
                isElement(previousSiblingOfNonEditable) &&
                previousSiblingOfNonEditable.childNodes.length
            ) {
                return getDeepestEditablePosition(
                    previousSiblingOfNonEditable,
                    nodeSize(previousSiblingOfNonEditable),
                );
            }
        }
    }

    return [deepEditableNode, deepEditableOffset];
}

export function previousLeaf(node, editable, skipInvisible = false) {
    let ancestor = node;
    while (ancestor && !ancestor.previousSibling && ancestor !== editable) {
        ancestor = ancestor.parentElement;
    }
    if (ancestor && ancestor !== editable) {
        if (skipInvisible && !isVisible(ancestor.previousSibling)) {
            return previousLeaf(ancestor.previousSibling, editable, skipInvisible);
        } else {
            const last = lastLeaf(ancestor.previousSibling);
            if (skipInvisible && !isVisible(last)) {
                return previousLeaf(last, editable, skipInvisible);
            } else {
                return last;
            }
        }
    }
}
export function nextLeaf(node, editable, skipInvisible = false) {
    let ancestor = node;
    while (ancestor && !ancestor.nextSibling && ancestor !== editable) {
        ancestor = ancestor.parentElement;
    }
    if (ancestor && ancestor !== editable) {
        if (skipInvisible && ancestor.nextSibling && !isVisible(ancestor.nextSibling)) {
            return nextLeaf(ancestor.nextSibling, editable, skipInvisible);
        } else {
            const first = firstLeaf(ancestor.nextSibling);
            if (skipInvisible && !isVisible(first)) {
                return nextLeaf(first, editable, skipInvisible);
            } else {
                return first;
            }
        }
    }
}

function hasPseudoElementContent(node, pseudoSelector) {
    const content = getComputedStyle(node, pseudoSelector).getPropertyValue("content");
    return content && content !== "none";
}

const NOT_A_NUMBER = /[^\d]/g;

export function areSimilarElements(node, node2) {
    if (![node, node2].every((n) => n?.nodeType === Node.ELEMENT_NODE)) {
        return false;
    }
    if (node.nodeName !== node2.nodeName) {
        return false;
    }
    for (const name of new Set([
        ...node.getAttributeNames(),
        ...node2.getAttributeNames(),
    ])) {
        if (name === "style") {
            if (!hasSameStyleAttributes(node, node2)) {
                return false;
            }
        } else if (name === "class") {
            if (!hasSameClasses(node, node2)) {
                return false;
            }
        } else if (node.getAttribute(name) !== node2.getAttribute(name)) {
            return false;
        }
    }
    if (
        [node, node2].some(
            (n) =>
                hasPseudoElementContent(n, ":before") ||
                hasPseudoElementContent(n, ":after"),
        )
    ) {
        return false;
    }
    if (isBlock(node)) {
        return false;
    }
    const nodeStyle = getComputedStyle(node);
    const node2Style = getComputedStyle(node2);
    if (node.matches("code.o_inline_code")) {
        if (
            nodeStyle.padding === node2Style.padding &&
            nodeStyle.margin === node2Style.margin
        ) {
            return true;
        }
    }
    return (
        !+nodeStyle.padding.replace(NOT_A_NUMBER, "") &&
        !+node2Style.padding.replace(NOT_A_NUMBER, "") &&
        !+nodeStyle.margin.replace(NOT_A_NUMBER, "") &&
        !+node2Style.margin.replace(NOT_A_NUMBER, "")
    );
}

export function hasSameStyleAttributes(node, node2) {
    const getNodeStyles = (node) =>
        (node.getAttribute("style") || "")
            .split(";")
            .map((style) => style.trim())
            .filter(Boolean);
    const [nodeStyles, node2Styles] = [node, node2].map(getNodeStyles);
    return (
        nodeStyles.length === node2Styles.length &&
        nodeStyles.every((style) => node2Styles.includes(style))
    );
}

export function hasSameClasses(node, node2) {
    const getNodeClasses = (node) =>
        (node.getAttribute("class") || "")
            .split(/\s+/)
            .map((c) => c.trim())
            .filter(Boolean);
    const [nodeClasses, node2Classes] = [node, node2].map(getNodeClasses);
    return (
        nodeClasses.length === node2Classes.length &&
        nodeClasses.every((cls) => node2Classes.includes(cls))
    );
}

export function isTextNode(node) {
    return node.nodeType === Node.TEXT_NODE;
}

export function isElement(node) {
    return node.nodeType === Node.ELEMENT_NODE;
}

export function isContentEditable(node) {
    const element = isTextNode(node) ? node.parentElement : node;
    return element && element.isContentEditable;
}

export function isContentEditableAncestor(node) {
    if (node.nodeType !== Node.ELEMENT_NODE) {
        return false;
    }
    return node.isContentEditable && node.matches("[contenteditable]");
}

function hasClassesSubset(node, node2) {
    const getNodeClasses = (n) => (n || "").trim().split(/\s+/).filter(Boolean);
    const [nodeClasses, node2Classes] = [node, node2].map(getNodeClasses);
    return nodeClasses.every((cls) => node2Classes.includes(cls));
}

function hasStylesSubset(node, node2) {
    const getNodeStyles = (n) =>
        (n || "")
            .split(";")
            .map((s) => s.trim())
            .filter(Boolean);
    const [nodeStyles, node2Styles] = [node, node2].map(getNodeStyles);
    return nodeStyles.every((style) => node2Styles.includes(style));
}

/**
 * @param {Node} node
 * @returns {boolean}
 */
export function isRedundantElement(node) {
    if (!node || node.nodeType !== Node.ELEMENT_NODE || !node.parentElement) {
        return false;
    }

    const closestEl = closestElement(node.parentElement, node.tagName);
    if (!closestEl) {
        return false;
    }

    for (const { name: attrName, value: nodeAttrVal } of node.attributes) {
        const closestElAttrVal = closestEl.getAttribute(attrName);

        if (!closestElAttrVal) {
            return false;
        }

        if (attrName === "class") {
            if (!hasClassesSubset(nodeAttrVal, closestElAttrVal)) {
                return false;
            }
        } else if (attrName === "style") {
            if (!hasStylesSubset(nodeAttrVal, closestElAttrVal)) {
                return false;
            }
        } else {
            if (nodeAttrVal !== closestElAttrVal) {
                return false;
            }
        }
    }

    return true;
}

export const PROTECTED_QWEB_SELECTOR = "[t-esc], [t-raw], [t-out], [t-field]";
