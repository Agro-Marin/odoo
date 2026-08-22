// @ts-check
/** @odoo-module native */

const RSTRIP_REGEXP = /(?=\n[ \t]*$)/;

/** @type {string | null} */
let translationContext = null;

const TCTX = "t-translation-context";

/**
 * @param {Node | null} node
 */
function getTranslationContext(node) {
    if (!node || node.nodeType !== Node.ELEMENT_NODE) {
        return translationContext ?? "";
    }
    const el = /** @type {Element} */ (node);
    if (el.hasAttribute(TCTX)) {
        return el.getAttribute(TCTX) ?? "";
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
            if (node.nodeValue?.trim() !== "") {
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

export function discardPendingTranslationContexts() {
    contextByTextNode.clear();
}

/**
 * @param {Node} node
 * @returns {Node}
 */
export function deepClone(node) {
    const clone = node.cloneNode(true);
    if (contextByTextNode.size) {
        remapTextNodeContexts(node, clone);
    }
    return clone;
}

/**
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
            const inserted = textNode.previousSibling;
            if (inserted?.nodeType === Node.TEXT_NODE) {
                const sibText = /** @type {Text} */ (inserted);
                sibText.data = sibText.data.trimEnd();
            }
        }
    }
}

/**
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
    if (xpath === null) {
        throw new Error(`Missing "expr" attribute on ${operation.outerHTML}`);
    }
    if (odoo.debug) {
        if (CLASS_CONTAINS_REGEX.test(xpath)) {
            const parent = operation.closest("t[t-inherit]");
            const templateName =
                parent?.getAttribute("t-name") ||
                parent?.getAttribute("t-inherit") ||
                "(unknown)";
            console.warn(
                `Error-prone use of @class in template "${templateName}" (or one of its inheritors).` +
                    " Use the hasclass(*classes) function to filter elements by their classes",
            );
        }
    }
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
            node.setAttribute(TCTX, getTranslationContext(node) ?? "");
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

const EXPRESSION_ATTRIBUTES = new Set([
    "column_invisible",
    "invisible",
    "readonly",
    "required",
    "t-elif",
    "t-if",
]);

const EXPRESSION_SEPARATORS = new Set(["and", "or", "&&", "||"]);

/**
 * @param {string} attributeName
 * @param {string} separator
 * @returns {string | null}
 */
function expressionOperator(attributeName, separator) {
    if (
        !EXPRESSION_ATTRIBUTES.has(attributeName) &&
        !attributeName.startsWith("decoration-")
    ) {
        return null;
    }
    const operator = separator.trim();
    return EXPRESSION_SEPARATORS.has(operator) ? operator : null;
}

const WORD_CHAR_REGEXP = /[\w$]/;

/**
 * @param {string} value
 * @param {string} operator
 * @returns {string[]}
 */
function splitOperands(value, operator) {
    const wordOperator = WORD_CHAR_REGEXP.test(operator[0]);
    const operands = [];
    let depth = 0;
    let quote = "";
    let start = 0;
    for (let i = 0; i < value.length; i++) {
        const char = value[i];
        if (quote) {
            if (char === "\\") {
                i++;
            } else if (char === quote) {
                quote = "";
            }
        } else if (char === "'" || char === '"') {
            quote = char;
        } else if ("([{".includes(char)) {
            depth++;
        } else if (")]}".includes(char)) {
            depth--;
        } else if (depth === 0 && value.startsWith(operator, i)) {
            const after = value[i + operator.length];
            if (
                !wordOperator ||
                (!WORD_CHAR_REGEXP.test(value[i - 1] ?? " ") &&
                    !WORD_CHAR_REGEXP.test(after ?? " "))
            ) {
                operands.push(value.slice(start, i));
                i += operator.length - 1;
                start = i + 1;
            }
        }
    }
    operands.push(value.slice(start));
    return operands;
}

/**
 * @param {string} operand
 * @returns {string}
 */
function normalizeOperand(operand) {
    let result = operand.trim();
    while (result.startsWith("(") && result.endsWith(")")) {
        let depth = 0;
        let wraps = true;
        for (let i = 0; i < result.length - 1 && wraps; i++) {
            depth += result[i] === "(" ? 1 : result[i] === ")" ? -1 : 0;
            wraps = depth > 0;
        }
        if (!wraps) {
            break;
        }
        result = result.slice(1, -1).trim();
    }
    return result;
}

/**
 * @param {string} value
 * @param {string} remove
 * @param {string} operator
 * @returns {string}
 */
function removeFromExpression(value, remove, operator) {
    const operands = splitOperands(value, operator);
    const normalized = operands.map(normalizeOperand);
    const target = splitOperands(remove, operator).map(normalizeOperand);
    for (let i = 0; i + target.length <= normalized.length; i++) {
        if (target.every((part, j) => part === normalized[i + j])) {
            const kept = [
                ...operands.slice(0, i),
                ...operands.slice(i + target.length),
            ];
            return kept.map((operand) => operand.trim()).join(` ${operator} `);
        }
    }
    return value;
}

const ATTRIBUTE_ELEMENT_KEYS = new Set(["name", "add", "remove", "separator"]);

/**
 * @param {Element} child
 */
function warnUnknownAttributeKeys(child) {
    const unknown = [...child.attributes]
        .map(({ name }) => name)
        .filter(
            (name) =>
                !ATTRIBUTE_ELEMENT_KEYS.has(name) &&
                !name.startsWith("data-oe-") &&
                !name.startsWith(TCTX),
        );
    if (unknown.length) {
        console.warn(
            `Ignored attribute(s) ${unknown.map((n) => `"${n}"`).join(", ")} on ` +
                `${child.outerHTML} — an <attribute> element only acts on ` +
                `"name", "add", "remove" and "separator". The operation is still ` +
                `applied, without them.`,
        );
    }
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
        if (attributeName === null) {
            throw new Error(`Missing "name" attribute on ${child.outerHTML}`);
        }
        const firstNode = child.childNodes[0];
        let value =
            firstNode?.nodeType === Node.TEXT_NODE
                ? /** @type {Text} */ (firstNode).data
                : "";

        warnUnknownAttributeKeys(child);
        const add = child.getAttribute("add") || "";
        const remove = child.getAttribute("remove") || "";
        if (add || remove) {
            if (firstNode?.nodeType === Node.TEXT_NODE) {
                throw new Error(
                    `Element <attribute name="${attributeName}"> with 'add' or 'remove' cannot contain text ${JSON.stringify(/** @type {Text} */ (firstNode).data)}`,
                );
            }
            const separator = child.getAttribute("separator") || ",";
            const operator = expressionOperator(attributeName, separator);
            if (operator) {
                let expression = target.getAttribute(attributeName) || "";
                if (remove) {
                    expression = removeFromExpression(expression, remove, operator);
                }
                if (add) {
                    expression = expression
                        ? `(${expression}) ${operator} (${add})`
                        : add;
                }
                value = expression;
                if (value) {
                    target.setAttribute(attributeName, value);
                } else {
                    target.removeAttribute(attributeName);
                }
                continue;
            }
            const toRemove = new Set(splitAndTrim(remove, separator));
            const values = splitAndTrim(
                target.getAttribute(attributeName) || "",
                separator,
            ).filter((s) => s && !toRemove.has(s));
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
 * @param {Node} node
 */
function removeNode(node) {
    const { nextSibling, previousSibling } = node;
    /** @type {ChildNode} */ (node).remove();
    if (
        nextSibling?.nodeType === Node.TEXT_NODE &&
        previousSibling?.nodeType === Node.TEXT_NODE &&
        previousSibling.parentElement?.firstChild === previousSibling
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
                loc?.firstChild?.replaceWith(deepClone(target));
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
                if (!operationContent) {
                    throw new Error(
                        `Replacing the root requires an element, got ${operation.outerHTML}`,
                    );
                }
                root = /** @type {Element} */ (deepClone(operationContent));
                if (target.hasAttribute("t-name")) {
                    root.setAttribute("t-name", target.getAttribute("t-name") ?? "");
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
 * @param {Element} operations
 * @param {string} [url=""]
 * @returns {Element}
 */
export function applyInheritance(root, operations, url = "") {
    translationContext = url.split("/")[1] ?? "";
    try {
        return applyOperations(root, operations, url);
    } finally {
        translationContext = null;
    }
}

/**
 * @param {Element} root
 * @param {Element} operations
 * @param {string} url
 * @returns {Element}
 */
function applyOperations(root, operations, url) {
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
                target.before(comment);
            } else {
                operation.prepend(comment);
            }
        }

        switch (position) {
            case "replace": {
                root = replace(root, target, operation);
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
    return root;
}
