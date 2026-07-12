// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/dom/xml - XML parse, serialize, create, and manipulate DOM elements */

import { isIterable } from "@web/core/utils/collections/arrays";

/**
 * XML document to create new elements from. The fact that this is a "text/xml"
 * document ensures that tagNames and attribute names are case sensitive.
 */
const serializer = new XMLSerializer();
const parser = new DOMParser();
const xmlDocument = parser.parseFromString("<templates/>", "text/xml");

/**
 * @param {Document} parsedDocument
 * @returns {boolean}
 */
function hasParsingError(parsedDocument) {
    return parsedDocument.getElementsByTagName("parsererror").length > 0;
}

/**
 * @param {string} str
 * @returns {Element}
 */
export function parseXML(str) {
    const xml = parser.parseFromString(str, "text/xml");
    if (hasParsingError(xml)) {
        throw new Error(
            `An error occured while parsing ${str}: ${
                xml.getElementsByTagName("parsererror")[0]?.textContent ?? ""
            }`,
        );
    }
    return xml.documentElement;
}

/**
 * @param {Element} xml
 * @returns {string}
 */
export function serializeXML(xml) {
    return serializer.serializeToString(xml);
}

/**
 * @param {Element | string} xml
 * @param {(el: Element, visitChildren: () => any) => any} callback
 */
export function visitXML(xml, callback) {
    const visit = (/** @type {Element} */ el) => {
        if (el) {
            let didVisitChildren = false;
            const visitChildren = () => {
                for (const child of el.children) {
                    visit(child);
                }
                didVisitChildren = true;
            };
            const shouldVisitChildren = callback(el, visitChildren);
            if (shouldVisitChildren !== false && !didVisitChildren) {
                visitChildren();
            }
        }
    };
    const xmlDoc = typeof xml === "string" ? parseXML(xml) : xml;
    visit(xmlDoc);
}

/**
 * @param {Element} parent
 * @param {Node | Node[] | void} node
 */
export function append(parent, node) {
    const nodes = Array.isArray(node) ? node : [node];
    parent.append(.../** @type {Node[]} */ (nodes.filter(Boolean)));
    return parent;
}

/**
 * Combines the existing value of a node attribute with new given parts. The glue
 * is the string used to join the parts.
 *
 * @param {Element} el
 * @param {string} attr
 * @param {string | string[]} parts
 * @param {string} [glue=" "]
 */
export function combineAttributes(el, attr, parts, glue = " ") {
    const allValues = [];
    if (el.hasAttribute(attr)) {
        allValues.push(el.getAttribute(attr));
    }
    parts = Array.isArray(parts) ? parts : [parts];
    parts = parts.filter((part) => !!part);
    allValues.push(...parts);
    el.setAttribute(attr, allValues.join(glue));
}

/**
 * XML equivalent of `document.createElement`.
 *
 * @param {string} tagName
 * @param {...any} args
 * @returns {Element}
 */
export function createElement(tagName, ...args) {
    const el = xmlDocument.createElement(tagName);
    for (const arg of args) {
        if (!arg) {
            continue;
        }
        if (isIterable(arg)) {
            // Children list
            el.append(...arg);
        } else if (typeof arg === "object") {
            // Attributes
            for (const name of Object.keys(arg)) {
                el.setAttribute(name, arg[name]);
            }
        }
    }
    return el;
}

/**
 * XML equivalent of `document.createTextNode`.
 *
 * @param {string} data
 * @returns {Text}
 */
export function createTextNode(data) {
    return xmlDocument.createTextNode(data);
}

/**
 * Removes the given attributes on the given element and returns them as a dictionnary.
 * @param {Element} el
 * @param {string[]} attributes
 * @returns {Record<string, string>}
 */
export function extractAttributes(el, attributes) {
    const attrs = Object.create(null);
    for (const attr of attributes) {
        attrs[attr] = el.getAttribute(attr) || "";
        el.removeAttribute(attr);
    }
    return attrs;
}

/**
 * @param {Node} [node]
 * @param {boolean} [lower=false]
 * @returns {string}
 */
export function getTag(node, lower = false) {
    const tag = node?.nodeName || "";
    return lower ? tag.toLowerCase() : tag;
}

/**
 * @param {Element} node
 * @param {Record<string, string>} attributes
 */
export function setAttributes(node, attributes) {
    for (const [name, value] of Object.entries(attributes)) {
        node.setAttribute(name, value);
    }
}

/**
 * Pretty-print an XML string with proper indentation.
 *
 * Regex-based formatter that handles elements, comments, CDATA,
 * DOCTYPE, processing instructions, and xmlns attributes.
 *
 * @param {string} xml raw XML string
 * @param {number} [indent=4] spaces per indentation level
 * @returns {string} formatted XML
 */
export function formatXML(xml, indent = 4) {
    const pad = " ".repeat(indent);
    // Collapse inter-tag whitespace, then split so each tag becomes a
    // separate token while preserving text content between tags.
    const tokens = xml
        .replace(/>\s+</g, "><")
        .replace(/</g, "~::~<")
        .replace(/\s*xmlns:/g, "~::~xmlns:")
        .replace(/\s*xmlns=/g, "~::~xmlns=")
        .split("~::~")
        .filter(Boolean);

    let depth = 0;
    let inComment = false;
    const lines = [];

    for (let ix = 0; ix < tokens.length; ix++) {
        const token = tokens[ix];

        // Comment / CDATA / DOCTYPE start
        if (/^<!/.test(token)) {
            lines.push(pad.repeat(depth) + token);
            inComment = true;
            if (/-->|]>|!DOCTYPE/.test(token)) {
                inComment = false;
            }
            continue;
        }
        // Comment / CDATA end
        if (/-->|]>/.test(token)) {
            lines.push(token);
            inComment = false;
            continue;
        }
        if (inComment) {
            lines.push(token);
            continue;
        }
        // Closing tag that directly follows its matching opening tag
        // (e.g. <field name="x">Text</field> → keep on one line).
        if (/^<\//.test(token)) {
            const prev = ix > 0 ? tokens[ix - 1] : "";
            const openTag = /^<([\w:.,-]+)/.exec(prev);
            const closeTag = /^<\/([\w:.,-]+)/.exec(token);
            if (openTag && closeTag && openTag[1] === closeTag[1]) {
                // Append to previous line instead of adding a new one.
                lines[lines.length - 1] += token;
                if (!inComment) {
                    depth = Math.max(0, depth - 1);
                }
            } else {
                // Clamp at 0: an unbalanced document (a stray closing tag)
                // would otherwise drive depth negative and crash
                // `" ".repeat(-1)` with a RangeError.
                depth = Math.max(0, depth - 1);
                lines.push(pad.repeat(depth) + token);
            }
        }
        // Self-closing tag (check anywhere in token, not just end —
        // the token may be "<tag/>text" when text follows a self-closer).
        else if (/^<\w/.test(token) && /\/>/.test(token) && !/<\//.test(token)) {
            lines.push(pad.repeat(depth) + token);
        }
        // Processing instruction <?...?>
        else if (/^<\?/.test(token)) {
            lines.push(pad.repeat(depth) + token);
        }
        // Opening tag (no self-close or closing tag anywhere in token)
        else if (/^<\w/.test(token) && !/<\//.test(token) && !/\/>/.test(token)) {
            lines.push(pad.repeat(depth++) + token);
        }
        // Opening + closing on same token: <el>text</el>
        else if (/^<\w/.test(token)) {
            lines.push(pad.repeat(depth) + token);
        }
        // xmlns continuation or bare text content
        else {
            lines.push(pad.repeat(depth) + token);
        }
    }

    return lines.join("\n");
}
