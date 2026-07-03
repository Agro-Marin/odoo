// @ts-check
/** @odoo-module native */

/** @module @web/core/template_inheritance - XPath-based QWeb template inheritance (apply, validate, deep clone) */

const RSTRIP_REGEXP = /(?=\n[ \t]*$)/;

/** @type {string | null} */
let translationContext = null;

const TCTX = "t-translation-context";

/**
 * @param {Node} node
 */
function getTranslationContext(node) {
    if (!node || node.nodeType !== Node.ELEMENT_NODE) {
        // Reached the root without finding a translation context.
        return translationContext ?? "";
    }
    const el = /** @type {Element} */ (node);
    if (el.hasAttribute(TCTX)) {
        return el.getAttribute(TCTX);
    }
    return getTranslationContext(el.parentElement);
}

const contextByTextNode = new Map();

/**
 * @param {Node} node
 */
function setTranslationContext(node) {
    switch (node.nodeType) {
        case Node.TEXT_NODE:
            if (node.nodeValue.trim() !== "") {
                contextByTextNode.set(node, translationContext);
            }
            break;
        case Node.ELEMENT_NODE:
            /** @type {Element} */ (node).setAttribute(
                TCTX,
                /** @type {string} */ (translationContext),
            );
            break;
    }
}

export function applyContextToTextNode() {
    for (const [textNode, context] of contextByTextNode) {
        const wrapper = document.createElement("t");
        wrapper.setAttribute(TCTX, context);
        textNode.before(wrapper);
        wrapper.appendChild(textNode);
    }
    contextByTextNode.clear();
}

/**
 * @param {Node} node
 * @returns {Node}
 */
export function deepClone(node) {
    // Native deep clone; O(n) in C++ instead of a per-node JS recursion that
    // spread childNodes at every level. The only reason the old recursion
    // existed was to carry over the `contextByTextNode` entries onto the
    // clones — so we replay just that mapping with a parallel TreeWalker, and
    // only when the map actually holds entries (the common boot path has an
    // empty map, so this is skipped entirely).
    const clone = node.cloneNode(true);
    if (contextByTextNode.size) {
        remapTextNodeContexts(node, clone);
    }
    return clone;
}

/**
 * Copy `contextByTextNode` entries from the text nodes of `original` onto the
 * matching text nodes of `clone`. `original` and `clone` are structurally
 * identical (clone is a deep clone of original), so a parallel in-order walk
 * of their text nodes lines them up one-to-one.
 *
 * @param {Node} original
 * @param {Node} clone
 */
function remapTextNodeContexts(original, clone) {
    if (original.nodeType === Node.TEXT_NODE) {
        if (contextByTextNode.has(original)) {
            contextByTextNode.set(clone, contextByTextNode.get(original));
        }
        return;
    }
    const originalWalker = document.createTreeWalker(original, NodeFilter.SHOW_TEXT);
    const cloneWalker = document.createTreeWalker(clone, NodeFilter.SHOW_TEXT);
    let originalNode;
    let cloneNode;
    while (
        (originalNode = originalWalker.nextNode()) &&
        (cloneNode = cloneWalker.nextNode())
    ) {
        if (contextByTextNode.has(originalNode)) {
            contextByTextNode.set(cloneNode, contextByTextNode.get(originalNode));
        }
    }
}

/**
 * The child nodes of operation represent new content to create before target or
 * or other elements to move before target from the target tree (tree from which target is part of).
 * Some processing of text nodes has to be done in order to normalize the situation.
 * Note: we assume that target has a parent element.
 * @param {Element} target
 * @param {Element} operation
 */
function addBefore(target, operation) {
    const nodes = getNodes(target, operation);
    if (!nodes.length) {
        return;
    }
    const { previousSibling } = target;
    target.before(...nodes);
    if (previousSibling?.nodeType === Node.TEXT_NODE) {
        const prevText = /** @type {Text} */ (previousSibling);
        const [text1, text2] = prevText.data.split(RSTRIP_REGEXP);
        prevText.data = text1.trimEnd();
        if (text2 && nodes.some((n) => n.nodeType !== Node.TEXT_NODE)) {
            const textNode = document.createTextNode(text2);
            target.before(textNode);
            if (textNode.previousSibling.nodeType === Node.TEXT_NODE) {
                const sibText = /** @type {Text} */ (textNode.previousSibling);
                sibText.data = sibText.data.trimEnd();
            }
        }
    }
}

/**
 * element is part of a tree. Here we return the root element of that tree.
 * Note: this root element is not necessarily the documentElement of the ownerDocument
 * of element (hence the following code).
 * @param {Element} element
 * @returns {Element}
 */
function getRoot(element) {
    while (element.parentElement) {
        element = element.parentElement;
    }
    return element;
}

const HASCLASS_REGEXP = /hasclass\(([^)]*)\)/g;
const CLASS_CONTAINS_REGEX = /contains\(@class.*\)/;
/**
 * @param {Element} operation
 * @returns {string}
 */
function getXpath(operation) {
    const xpath = operation.getAttribute("expr");
    if (odoo.debug) {
        if (CLASS_CONTAINS_REGEX.test(xpath)) {
            const parent = operation.closest("t[t-inherit]");
            const templateName =
                parent.getAttribute("t-name") || parent.getAttribute("t-inherit");
            console.warn(
                `Error-prone use of @class in template "${templateName}" (or one of its inheritors).` +
                    " Use the hasclass(*classes) function to filter elements by their classes",
            );
        }
    }
    // hasclass does not exist in XPath 1.0 but is a custom function defined server side (see _hasclass) usable in lxml.
    // Here we have to replace it by a complex condition (which is not nice).
    // Note: we assume that classes do not contain the 2 chars , and )
    return xpath.replaceAll(HASCLASS_REGEXP, (_, capturedGroup) =>
        capturedGroup
            .split(",")
            .map(
                (/** @type {string} */ c) =>
                    `contains(concat(' ', @class, ' '), ' ${c.trim().slice(1, -1)} ')`,
            )
            .join(" and "),
    );
}

/**
 * @param {Element} element
 * @param {Element} operation
 * @returns {Node|null}
 */
function getNode(element, operation) {
    const root = getRoot(element);
    // `doc.evaluate` (below) requires `root` to be attached to a document.
    // `root` is normally already the documentElement of its own Document
    // (getClone / applyInheritance keep it that way), so re-adopting it into a
    // fresh Document on every operation — O(tree) × hundreds of operations at
    // boot — is pure waste. Adopt only when `root` is actually detached, i.e.
    // right after it's been replaced (replace/outer builds a fresh root).
    if (root.ownerDocument?.documentElement !== root) {
        new Document().appendChild(root);
    }
    if (operation.tagName === "xpath") {
        const xpath = getXpath(operation);
        const result = root.ownerDocument.evaluate(
            xpath,
            root,
            null,
            XPathResult.FIRST_ORDERED_NODE_TYPE,
        );
        return result.singleNodeValue;
    }
    const attributes = [...operation.attributes].filter(
        (attr) => !attr.name.startsWith(TCTX),
    );
    for (const elem of root.querySelectorAll(operation.tagName)) {
        if (
            attributes.every(
                ({ name, value }) =>
                    name === "position" || elem.getAttribute(name) === value,
            )
        ) {
            return elem;
        }
    }
    return null;
}

/**
 * @param {Element} element
 * @param {Element} operation
 * @returns {Element}
 */
function getElement(element, operation) {
    const node = getNode(element, operation);
    if (!node) {
        throw new Error(
            `Element '${operation.outerHTML}' cannot be located in element tree`,
        );
    }
    if (!(node instanceof Element)) {
        throw new Error(`Found node ${node} instead of an element`);
    }
    return node;
}

/**
 * @param {Element} element
 * @param {Element} operation
 * @returns {Node[]}
 */
function getNodes(element, operation) {
    const nodes = [];
    for (const childNode of operation.childNodes) {
        if (
            /** @type {Element} */ (childNode).tagName === "xpath" &&
            /** @type {Element} */ (childNode).getAttribute?.("position") === "move"
        ) {
            const node = getElement(element, /** @type {Element} */ (childNode));
            node.setAttribute(TCTX, getTranslationContext(node));
            removeNode(node);
            nodes.push(node);
        } else {
            setTranslationContext(childNode);
            nodes.push(childNode);
        }
    }
    return nodes;
}

/**
 * @param {string} str
 * @param {string} separator
 */
function splitAndTrim(str, separator) {
    return str.split(separator).map((s) => s.trim());
}

/**
 * @param {Element} target
 * @param {Element} operation
 */
function modifyAttributes(target, operation) {
    for (const child of operation.children) {
        if (child.tagName !== "attribute") {
            continue;
        }
        const attributeName = child.getAttribute("name");
        const firstNode = child.childNodes[0];
        let value =
            firstNode?.nodeType === Node.TEXT_NODE
                ? /** @type {Text} */ (firstNode).data
                : "";

        const add = child.getAttribute("add") || "";
        const remove = child.getAttribute("remove") || "";
        if (add || remove) {
            if (firstNode?.nodeType === Node.TEXT_NODE) {
                throw new Error(
                    `Useless element content ${/** @type {Element} */ (firstNode).outerHTML}`,
                );
            }
            const separator = child.getAttribute("separator") || ",";
            const toRemove = new Set(splitAndTrim(remove, separator));
            const values = splitAndTrim(
                target.getAttribute(attributeName) || "",
                separator,
            ).filter((s) => !toRemove.has(s));
            values.push(...splitAndTrim(add, separator).filter((s) => s));
            value = values.join(separator);
        }

        if (value) {
            target.setAttribute(attributeName, value);
            if (!(add || remove)) {
                target.setAttribute(
                    `t-translation-context-${attributeName}`,
                    /** @type {string} */ (translationContext),
                );
            }
        } else {
            target.removeAttribute(attributeName);
        }
    }
}

/**
 * Remove node and normalize surrounding text nodes (if any)
 * Note: we assume that node has a parent element
 * @param {Node} node
 */
function removeNode(node) {
    const { nextSibling, previousSibling } = node;
    /** @type {ChildNode} */ (node).remove();
    if (
        nextSibling?.nodeType === Node.TEXT_NODE &&
        previousSibling?.nodeType === Node.TEXT_NODE &&
        previousSibling.parentElement.firstChild === previousSibling
    ) {
        /** @type {Text} */ (previousSibling).data = /** @type {Text} */ (
            previousSibling
        ).data.trimEnd();
    }
}

/**
 * @param {Element} root
 * @param {Element} target
 * @param {Element} operation
 */
function replace(root, target, operation) {
    const mode = operation.getAttribute("mode") || "outer";
    switch (mode) {
        case "outer": {
            const result = operation.ownerDocument.evaluate(
                ".//*[text()='$0']",
                operation,
                null,
                XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,
            );
            target.setAttribute(TCTX, getTranslationContext(target));
            for (let i = 0; i < result.snapshotLength; i++) {
                const loc = result.snapshotItem(i);
                loc.firstChild.replaceWith(deepClone(target));
            }
            if (target.parentElement) {
                const nodes = getNodes(target, operation);
                target.replaceWith(...nodes);
            } else {
                let operationContent = null;
                let comment = null;
                for (const child of operation.childNodes) {
                    if (child.nodeType === Node.ELEMENT_NODE) {
                        setTranslationContext(child);
                        operationContent = child;
                        break;
                    }
                    if (child.nodeType === Node.COMMENT_NODE) {
                        comment = child;
                    }
                }
                root = /** @type {Element} */ (deepClone(operationContent));
                if (target.hasAttribute("t-name")) {
                    root.setAttribute("t-name", target.getAttribute("t-name"));
                }
                if (comment) {
                    root.prepend(comment);
                }
            }
            break;
        }
        case "inner":
            target.replaceChildren();
            for (const node of [...operation.childNodes]) {
                setTranslationContext(node);
                target.append(node);
            }
            break;
        default:
            throw new Error(`Invalid mode attribute: '${mode}'`);
    }
    return root;
}

/**
 * @param {Element} root
 * @param {Element} operations is a single element whose children represent operations to perform on root
 * @param {string} [url=""]
 * @returns {Element} root modified (in place) by the operations
 */
export function applyInheritance(root, operations, url = "") {
    translationContext = url.split("/")[1] ?? ""; // use addon name as context
    for (const operation of operations.children) {
        const target = getElement(root, operation);
        const position = operation.getAttribute("position") || "inside";

        if (odoo.debug && url) {
            const attributes = [...operation.attributes].map(
                ({ name, value }) =>
                    `${name}=${JSON.stringify(name === "position" ? position : value)}`,
            );
            const comment = document.createComment(
                ` From file: ${url} ; ${attributes.join(" ; ")} `,
            );
            if (position === "attributes") {
                target.before(comment); // comment won't be visible if target is root
            } else {
                operation.prepend(comment);
            }
        }

        switch (position) {
            case "replace": {
                root = replace(root, target, operation); // root can be replaced (see outer mode)
                break;
            }
            case "attributes": {
                modifyAttributes(target, operation);
                break;
            }
            case "inside": {
                const sentinel = document.createElement("sentinel");
                target.append(sentinel);
                addBefore(sentinel, operation);
                removeNode(sentinel);
                break;
            }
            case "after": {
                const sentinel = document.createElement("sentinel");
                target.after(sentinel);
                addBefore(sentinel, operation);
                removeNode(sentinel);
                break;
            }
            case "before": {
                addBefore(target, operation);
                break;
            }
            default:
                throw new Error(`Invalid position attribute: '${position}'`);
        }
    }
    translationContext = null;
    return root;
}
