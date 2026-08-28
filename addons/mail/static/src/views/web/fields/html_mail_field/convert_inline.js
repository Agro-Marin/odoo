/** @odoo-module native */
import { isBlock } from "@html_editor/utils/blocks";
import { getAdjacentPreviousSiblings } from "@html_editor/utils/dom_traversal";
import { fonts } from "@html_editor/utils/fonts";
import { getImageSrc } from "@html_editor/utils/image";
import { loadImage } from "@html_editor/utils/image_processing";
import { blendColors } from "@web/core/utils/format/colors";

import {
    _computeStyleAndSpecificityOnRules,
    _getRightmostSelectorTokens,
    splitSelectorAroundCommasOutsideParentheses,
} from "./css_specificity.js";

export { splitSelectorAroundCommasOutsideParentheses };

/**
 * @typedef {CSSStyleDeclaration & Record<string, string>} IndexableStyle
 */
/**
 * @typedef {Object<string, string>} StyleMap
 */
/**
 * @typedef {Object} CssRule
 * @property {string} selector
 * @property {StyleMap} [style]
 * @property {number} [specificity]
 * @property {CSSStyleRule} [rawRule]
 */

/**
 * @param {Node} node
 * @param {Node} [root]
 * @returns {Node[]}
 */
function parentsGet(node, root = undefined) {
    const parents = [];
    while (node) {
        parents.unshift(node);
        if (node === root) {
            break;
        }
        node = node.parentNode;
    }
    return parents;
}

/**
 * @param {Node} node1
 * @param {Node} node2
 * @param {Node} [root]
 * @returns {Node|null}
 */
function commonParentGet(node1, node2, root = undefined) {
    if (!node1 || !node2) {
        return null;
    }
    const n1p = parentsGet(node1, root);
    const n2p = parentsGet(node2, root);
    while (n1p.length > 1 && n1p[1] === n2p[1]) {
        n1p.shift();
        n2p.shift();
    }
    return n1p[0] === n2p[0] ? n1p[0] : null;
}

const RE_COL_MATCH = /(^| )col(-[\w\d]+)*( |$)/;
const RE_COL_MD_MATCH = /(^| )col-md(-\d+)*( |$)/;
const RE_OFFSET_MATCH = /(^| )offset(-[\w\d]+)+( |$)/;
const RE_OFFSET_MD_MATCH = /(^| )offset-md(-\d+)+( |$)/;
const RE_PADDING_MATCH = /[ ]*padding[^;]*;/g;
const RE_PADDING = /([\d.]+)/;
const RE_WHITESPACE = /^[\s\u200b]*$/;
const SELECTORS_IGNORE =
    /(^\*$|:hover|:before|:after|:active|:link|:visited|:checked|:disabled|::|')|@page/;
const RE_THEME_COLOR_CLASS = /^bg-o-color-\d+$/;
const CONVERT_INLINE_BLACKLIST_CLASSES = ["o_mail_redirect"];
const GENERATED_ATTRIBUTE = "data-o-mail-generated";
const FONT_PROPERTIES_TO_INHERIT = [
    "color",
    "font-size",
    "font-family",
    "font-weight",
    "font-style",
    "text-decoration",
    "text-transform",
    "text-align",
];
/** @type {Object<string, string|number>} */
export const TABLE_ATTRIBUTES = {
    cellspacing: 0,
    cellpadding: 0,
    border: 0,
    width: "100%",
    align: "center",
    role: "presentation",
};
/** @type {StyleMap} */
export const TABLE_STYLES = {
    "border-collapse": "separate",
    "border-spacing": "0px",
    "text-align": "inherit",
    "font-size": "unset",
    "line-height": "inherit",
};

/** @type {StyleMap} */
const BASIC_THEME_TABLE_STYLES = {
    "background-color": "transparent",
    color: "inherit",
};

/** @type {Object<string, string[]>} */
const GROUPED_STYLES = {
    border: [
        "border-top-width",
        "border-right-width",
        "border-bottom-width",
        "border-left-width",
        "border-top-style",
        "border-right-style",
        "border-bottom-style",
        "border-left-style",
        "border-top-color",
        "border-right-color",
        "border-bottom-color",
        "border-left-color",
    ],
    padding: ["padding-top", "padding-bottom", "padding-left", "padding-right"],
    margin: ["margin-top", "margin-bottom", "margin-left", "margin-right"],
    "border-radius": [
        "border-top-left-radius",
        "border-top-right-radius",
        "border-bottom-right-radius",
        "border-bottom-left-radius",
    ],
};
/** @type {Object<string, string[]>} */
const GROUPED_STYLES_SHORTHANDS = {
    border: [
        "border",
        "border-top",
        "border-right",
        "border-bottom",
        "border-left",
        "border-width",
        "border-style",
        "border-color",
    ],
    padding: ["padding"],
    margin: ["margin"],
    "border-radius": ["border-radius"],
};
const STYLE_INITIAL_VALUES = ["0px", "none", "medium"];

/** @type {Set<string>} */
const FLEX_LAYOUT_PROPERTIES = new Set([
    "flex",
    "flex-grow",
    "flex-shrink",
    "flex-basis",
    "flex-direction",
    "flex-wrap",
    "flex-flow",
]);
/**
 * @param {string} propertyName
 * @param {string} propertyValue
 * @returns {boolean}
 */
function isDroppedFlexDeclaration(propertyName, propertyValue) {
    return (
        FLEX_LAYOUT_PROPERTIES.has(propertyName) ||
        (propertyName === "display" &&
            (propertyValue === "flex" || propertyValue === "inline-flex"))
    );
}

/** @param {HTMLElement} element */
export function addTables(element) {
    const isInBasicTheme = Boolean(element.querySelector(".o_layout.o_basic_theme"));
    for (const snippet of element.querySelectorAll(
        ".o_mail_snippet_general, .o_layout",
    )) {
        if (snippet.nodeName === "TABLE") {
            continue;
        }
        if (isInBasicTheme) {
            for (const [property, value] of Object.entries(BASIC_THEME_TABLE_STYLES)) {
                snippet.style.setProperty(property, value);
            }
        }
        const table = _createTable(snippet.attributes);

        const row = document.createElement("tr");
        /**
         * @type {HTMLElement}
         */
        let col = document.createElement("td");
        _markGenerated(row, col);
        row.appendChild(col);
        if (snippet.classList.contains("o_basic_theme")) {
            const div = document.createElement("div");
            _markGenerated(div);
            div.classList.add("o_apple_wrapper_padding");
            col.appendChild(div);
            col = div;
            const style = document.createElement("style");
            const padding = "34px";
            style.textContent =
                `@media{@media{.o_basic_theme div.o_apple_wrapper_padding{padding:${snippet.style.padding};}}}` +
                `@media(min-width:737px){@media{@media{.o_basic_theme div.o_apple_wrapper_padding{padding-left:${padding};}}}}`;
            div.before(style);
        }
        table.appendChild(row);

        for (const child of [...snippet.childNodes]) {
            col.appendChild(child);
        }
        snippet.before(table);
        snippet.remove();

        const childTables = [...col.children].filter(
            (child) => child.nodeName === "TABLE",
        );
        if (!childTables.length) {
            const tableB = _createTable();
            const rowB = document.createElement("tr");
            const colB = document.createElement("td");
            _markGenerated(rowB, colB);

            rowB.appendChild(colB);
            tableB.appendChild(rowB);
            for (const child of [...col.childNodes]) {
                colB.appendChild(child);
            }
            col.appendChild(tableB);
        }
    }
}
/** @param {HTMLElement} element */
function attachmentThumbnailToLinkImg(element) {
    const links = [
        .../** @type {NodeListOf<HTMLAnchorElement>} */ (
            element.querySelectorAll(`a[href*="/web/content/"][data-mimetype]:empty`)
        ),
    ].filter((link) => RE_WHITESPACE.test(link.textContent));
    for (const link of links) {
        const image = document.createElement("img");
        image.setAttribute(
            "src",
            _getStylePropertyValue(link, "background-image").replace(
                /(^url\(['"])|(['"]\)$)/g,
                "",
            ),
        );
        image.setAttribute("height", String(Math.max(1, _getHeight(link))));
        image.setAttribute("width", String(Math.max(1, _getWidth(link))));
        link.prepend(image);
    }
}
/** @param {Element} element */
function _flattenNestedRows(element) {
    for (const rowInColumn of [
        .../** @type {NodeListOf<HTMLElement>} */ (element.querySelectorAll(".row")),
    ].filter((row) => RE_COL_MATCH.test(row.parentElement.className))) {
        const parentColumn = rowInColumn.parentElement;
        const previous = rowInColumn.previousElementSibling;
        if (previous && previous.classList.contains("o_fake_table")) {
            previous.append(rowInColumn);
        } else {
            _wrap(rowInColumn, "div", "o_fake_table");
        }
        const rowStyle = /** @type {IndexableStyle} */ (getComputedStyle(rowInColumn));
        const columnStyle = /** @type {IndexableStyle} */ (
            getComputedStyle(parentColumn)
        );
        const parentColumnStyle = /** @type {IndexableStyle} */ (parentColumn.style);
        const rowInColumnStyle = /** @type {IndexableStyle} */ (rowInColumn.style);
        for (const side of ["left", "right"]) {
            const negativeMargin = +rowStyle[`margin-${side}`].replace("px", "");
            const columnPadding = +columnStyle[`padding-${side}`].replace("px", "");
            if (negativeMargin < 0 && columnPadding >= Math.abs(negativeMargin)) {
                parentColumnStyle[`padding-${side}`] =
                    `${columnPadding + negativeMargin}px`;
                rowInColumnStyle[`margin-${side}`] = "0";
            }
        }
    }
}
/** @param {Element} element */
function _normalizeMasonryGrids(element) {
    for (const masonryTopInnerContainer of /** @type {NodeListOf<HTMLElement>} */ (
        element.querySelectorAll(".s_masonry_block > .container")
    )) {
        masonryTopInnerContainer.style.setProperty("height", "100%");
    }
    for (const masonryGrid of /** @type {NodeListOf<HTMLElement>} */ (
        element.querySelectorAll(".o_masonry_grid_container")
    )) {
        masonryGrid.style.setProperty("padding", "0");
        for (const fakeTable of [
            .../** @type {HTMLCollectionOf<HTMLElement>} */ (masonryGrid.children),
        ].filter((c) => c.classList.contains("o_fake_table"))) {
            fakeTable.style.setProperty("height", _getHeight(fakeTable) + "px");
        }
    }
    for (const masonryRow of /** @type {NodeListOf<HTMLElement>} */ (
        element.querySelectorAll(
            ".o_masonry_grid_container > .o_fake_table > .row.h-100",
        )
    )) {
        masonryRow.style.removeProperty("height");
        masonryRow.parentElement.style.setProperty("height", "100%");
    }
}
/**
 * @param {HTMLElement} container
 * @returns {HTMLTableElement}
 */
function _replaceContainerWithTable(container) {
    const table = _createTable(container.attributes);
    for (const child of [...container.childNodes]) {
        table.append(child);
    }
    table.classList.remove("container", "container-fluid", "o_fake_table");
    if (!table.className) {
        table.removeAttribute("class");
    }
    container.before(table);
    container.remove();
    return table;
}
/**
 * @param {HTMLElement} tr
 * @returns {HTMLElement[]}
 */
function _normalizeBootstrapColumns(tr) {
    const bootstrapColumns = [...tr.children].filter((column) => {
        let match = column.className && column.className.match(RE_COL_MATCH);
        const size = match ? _getColumnSize(column) : undefined;
        while (match) {
            column.classList.remove(match[0].trim());
            match = column.className && column.className.match(RE_COL_MATCH);
        }
        if (size !== undefined) {
            column.classList.add(`col${size ? `-${size}` : ``}`);
        }
        return size !== undefined;
    });

    const flexColumns = bootstrapColumns.filter(
        (column) => !/\d/.test(column.className.match(RE_COL_MATCH)[0] || "0"),
    );
    const colTotalSize = bootstrapColumns
        .map((child) => _getColumnSize(child) + _getColumnOffsetSize(child))
        .reduce((a, b) => a + b, 0);
    const colSize = Math.max(1, Math.round((12 - colTotalSize) / flexColumns.length));
    for (const flexColumn of flexColumns) {
        flexColumn.classList.remove(flexColumn.className.match(RE_COL_MATCH)[0].trim());
        flexColumn.classList.add(`col-${colSize}`);
    }

    let columnIndex = 0;
    for (const bootstrapColumn of [...bootstrapColumns]) {
        const offsetSize = _getColumnOffsetSize(bootstrapColumn);
        if (offsetSize) {
            const newColumn = document.createElement("div");
            _markGenerated(newColumn);
            newColumn.classList.add(`col-${offsetSize}`);
            let match = bootstrapColumn.className.match(RE_OFFSET_MATCH);
            while (match) {
                bootstrapColumn.classList.remove(match[0].trim());
                match = bootstrapColumn.className.match(RE_OFFSET_MATCH);
            }
            bootstrapColumn.before(newColumn);
            bootstrapColumns.splice(columnIndex, 0, newColumn);
            columnIndex++;
        }
        columnIndex++;
    }
    return bootstrapColumns;
}
/**
 * @param {HTMLTableRowElement} tr
 * @param {HTMLElement[]} bootstrapColumns
 * @param {number} containerWidth
 */
function _layoutColumnsIntoGrid(tr, bootstrapColumns, containerWidth) {
    let grid = _createColumnGrid();
    let gridIndex = 0;
    let currentRow = /** @type {HTMLTableRowElement} */ (tr.cloneNode());
    tr.after(currentRow);
    /** @type {HTMLTableCellElement|undefined} */
    let currentCol;
    let columnIndex = 0;
    for (const bootstrapColumn of bootstrapColumns) {
        const columnSize = _getColumnSize(bootstrapColumn);
        if (gridIndex + columnSize < 12) {
            currentCol = grid[gridIndex];
            _applyColspan(currentCol, columnSize, containerWidth);
            gridIndex += columnSize;
        } else if (gridIndex + columnSize === 12) {
            currentCol = grid[gridIndex];
            _applyColspan(currentCol, columnSize, containerWidth);
            currentRow.append(...grid.filter((td) => td.getAttribute("colspan")));
            if (columnIndex !== bootstrapColumns.length - 1) {
                const previousRow = currentRow;
                currentRow = /** @type {HTMLTableRowElement} */ (
                    currentRow.cloneNode()
                );
                currentRow.removeAttribute("id");
                previousRow.after(currentRow);
                grid = _createColumnGrid();
                gridIndex = 0;
            }
        } else {
            if (gridIndex < 12) {
                _applyColspan(grid[gridIndex], 12 - gridIndex, containerWidth);
            }
            currentRow.append(...grid.filter((td) => td.getAttribute("colspan")));
            const previousRow = currentRow;
            currentRow = /** @type {HTMLTableRowElement} */ (currentRow.cloneNode());
            currentRow.removeAttribute("id");
            previousRow.after(currentRow);
            grid = _createColumnGrid();
            currentCol = grid[0];
            _applyColspan(currentCol, columnSize, containerWidth);
            gridIndex = columnSize;
        }
        if (columnIndex === bootstrapColumns.length - 1) {
            if (gridIndex < 12) {
                _applyColspan(grid[gridIndex], 12 - gridIndex, containerWidth);
            }
            currentRow.append(...grid.filter((td) => td.getAttribute("colspan")));
        }
        if (currentCol) {
            for (const attr of bootstrapColumn.attributes) {
                if (attr.name !== "colspan") {
                    currentCol.setAttribute(attr.name, attr.value);
                }
            }
            const colMatch = bootstrapColumn.className.match(RE_COL_MATCH);
            currentCol.classList.remove(colMatch[0].trim());
            if (!currentCol.className) {
                currentCol.removeAttribute("class");
            }
            for (const child of [...bootstrapColumn.childNodes]) {
                currentCol.append(child);
            }
            _applyColspan(
                currentCol,
                +currentCol.getAttribute("colspan"),
                containerWidth,
            );
        }
        columnIndex++;
    }
}
/**
 * @param {HTMLElement} bootstrapRow
 * @param {number} containerWidth
 */
function _convertBootstrapRowToRows(bootstrapRow, containerWidth) {
    const tr = document.createElement("tr");
    _markGenerated(tr);
    for (const attr of bootstrapRow.attributes) {
        tr.setAttribute(attr.name, attr.value);
    }
    tr.classList.remove("row");
    if (!tr.className) {
        tr.removeAttribute("class");
    }
    for (const child of [...bootstrapRow.childNodes]) {
        tr.append(child);
    }
    bootstrapRow.before(tr);
    bootstrapRow.remove();

    const bootstrapColumns = _normalizeBootstrapColumns(tr);
    _layoutColumnsIntoGrid(tr, bootstrapColumns, containerWidth);
    tr.remove();
}
/** @param {Element} element */
function _stackTablesInCells(element) {
    const tds = [...element.querySelectorAll("td")]
        .filter(
            (td) =>
                (!td.hasAttribute(GENERATED_ATTRIBUTE) ||
                    td.classList.contains("o_converted_col")) &&
                td.children.length > 1 &&
                [...td.children].every((child) => child.nodeName === "TABLE"),
        )
        .reverse();
    for (const td of tds) {
        const table = _createTable();
        const trs = [...td.children]
            .map((child) => _wrap(child, "td"))
            .map((wrappedChild) => _wrap(wrappedChild, "tr"));
        trs[0].before(table);
        table.append(...trs);
    }
}
/** @param {Element} element */
export function bootstrapToTable(element) {
    _flattenNestedRows(element);
    _normalizeMasonryGrids(element);

    const containers = /** @type {NodeListOf<HTMLElement>} */ (
        element.querySelectorAll(".container, .container-fluid, .o_fake_table")
    );
    for (const container of containers) {
        container.setAttribute("o-temp-width", String(_getWidth(container)));
    }
    for (const container of [...containers].filter((n) =>
        [...n.children].some((c) => c.classList.contains("row")),
    )) {
        const containerWidth = parseFloat(container.getAttribute("o-temp-width"));
        const table = _replaceContainerWithTable(container);

        for (const row of [...table.children].filter(
            (child) => isBlock(child) && !child.classList.contains("row"),
        )) {
            const newCol = _wrap(row, "div", "col-12");
            _wrap(newCol, "div", "row");
        }

        for (const bootstrapRow of [...table.children].filter((c) =>
            c.classList.contains("row"),
        )) {
            _convertBootstrapRowToRows(bootstrapRow, containerWidth);
        }
    }
    for (const node of element.querySelectorAll("[o-temp-width]")) {
        node.removeAttribute("o-temp-width");
    }
    _stackTablesInCells(element);
}
/** @param {Element} element */
export function cardToTable(element) {
    for (const card of element.querySelectorAll(".card")) {
        if (card.nodeName === "TABLE") {
            continue;
        }
        const table = _createTable(card.attributes);
        table.style.removeProperty("overflow");
        /** @type {HTMLTableRowElement[]} */
        const cardImgTopSuperRows = [];
        for (const child of [...card.childNodes]) {
            const row = document.createElement("tr");
            const col = document.createElement("td");
            _markGenerated(row, col);
            if (!["IMG", "A"].includes(child.nodeName) && isBlock(child)) {
                const childElement = /** @type {Element} */ (child);
                for (const attr of childElement.attributes) {
                    col.setAttribute(attr.name, attr.value);
                }
                for (const descendant of [...child.childNodes]) {
                    col.append(descendant);
                }
                child.remove();
            } else if (child.nodeType === Node.TEXT_NODE) {
                if (child.textContent.replace(RE_WHITESPACE, "").length) {
                    col.append(child);
                } else {
                    continue;
                }
            } else {
                col.append(child);
            }
            const subTable = _createTable();
            subTable.style.height = "100%";
            const superRow = document.createElement("tr");
            const superCol = document.createElement("td");
            _markGenerated(superRow, superCol);
            row.append(col);
            subTable.append(row);
            superCol.append(subTable);
            superRow.append(superCol);
            table.append(superRow);
            if (child.nodeType === Node.ELEMENT_NODE) {
                const childElement = /** @type {Element} */ (child);
                const hasImgTop = [
                    childElement,
                    ...childElement.querySelectorAll(".card-img-top"),
                ].some(
                    (node) =>
                        node.classList &&
                        node.classList.contains("card-img-top") &&
                        node.closest &&
                        node.closest(".card") === table,
                );
                if (hasImgTop) {
                    cardImgTopSuperRows.push(superRow);
                }
            }
        }
        card.before(table);
        card.remove();
        if (cardImgTopSuperRows.length) {
            const smallestCardImgRow = Math.min(
                ...cardImgTopSuperRows.map((row) => row.clientHeight),
            );
            for (const row of cardImgTopSuperRows) {
                row.style.height = smallestCardImgRow + "px";
            }
        }
    }
}
/**
 * @param {HTMLElement} element
 * @returns {{tags: Set<string>, classes: Set<string>, ids: Set<string>}}
 */
function _collectSubtreeSelectorTokens(element) {
    const tags = new Set();
    const classes = new Set();
    const ids = new Set();
    for (const node of element.querySelectorAll("*")) {
        tags.add(node.nodeName.toLowerCase());
        if (node.id) {
            ids.add(node.id);
        }
        for (const className of node.classList) {
            classes.add(className);
        }
    }
    return { tags, classes, ids };
}
/**
 * @param {HTMLElement} element
 * @param {CssRule[]} cssRules
 * @returns {Map<HTMLElement, CssRule[]>}
 */
function _matchRulesToNodes(element, cssRules) {
    const subtree = _collectSubtreeSelectorTokens(element);
    /** @type {Map<HTMLElement, CssRule[]>} */
    const nodeToRules = new Map();
    /** @type {CssRule[]} */
    const rulesToProcess = [];
    for (const rule of cssRules) {
        const { tag, classes, ids } = _getRightmostSelectorTokens(rule.selector);
        if (
            (tag && !subtree.tags.has(tag)) ||
            classes.some((className) => !subtree.classes.has(className)) ||
            ids.some((id) => !subtree.ids.has(id))
        ) {
            continue;
        }
        /** @type {NodeListOf<HTMLElement>} */
        let nodes;
        try {
            nodes = element.querySelectorAll(rule.selector);
        } catch {
            continue;
        }
        if (nodes.length) {
            rulesToProcess.push(rule);
        }
        for (const node of nodes) {
            if (node.hasAttribute(GENERATED_ATTRIBUTE)) {
                continue;
            }
            const nodeRules = nodeToRules.get(node);
            if (!nodeRules) {
                nodeToRules.set(node, [rule]);
            } else {
                nodeRules.push(rule);
            }
        }
    }
    _computeStyleAndSpecificityOnRules(rulesToProcess);
    for (const rules of nodeToRules.values()) {
        rules.sort((a, b) => a.specificity - b.specificity);
    }
    return nodeToRules;
}
/**
 * @param {HTMLElement} node
 * @param {StyleMap} css
 * @param {HTMLElement} styleProbe
 * @param {(() => void)[]} writes
 */
function _prepareStyleAttributeWrite(node, css, styleProbe, writes) {
    let style = node.getAttribute("style") || "";
    style = style.replace(/!important/g, "");
    style = style
        .split(";")
        .filter((declaration) => {
            const separator = declaration.indexOf(":");
            if (separator === -1) {
                return true;
            }
            const name = declaration.slice(0, separator).trim();
            const value = declaration.slice(separator + 1).trim();
            return !isDroppedFlexDeclaration(name, value);
        })
        .join(";");
    styleProbe.style.cssText = style;
    for (const [key, value] of Object.entries(css)) {
        if (!styleProbe.style.getPropertyValue(key)) {
            style = `${key}:${value};${style}`;
        }
    }
    style = correctBorderAttributes(style);
    if (!style.trim() || node.nodeName === "T") {
        writes.push(() => {
            node.removeAttribute("style");
        });
    } else {
        writes.push(() => {
            node.setAttribute("style", style);
            if (node.style.width) {
                node.setAttribute("width", node.style.width.replace("px", "").trim());
            }
        });
    }
}
/**
 * @param {HTMLElement} node
 * @param {(() => void)[]} writes
 */
function _prepareThemeColorClassWrite(node, writes) {
    const themeColorClasses = [...node.classList].filter((c) =>
        RE_THEME_COLOR_CLASS.test(c),
    );
    if (!themeColorClasses.length) {
        return;
    }
    writes.push(() => {
        for (const cls of themeColorClasses) {
            node.classList.remove(cls);
        }
        if (!node.classList.length) {
            node.removeAttribute("class");
        }
    });
}
/**
 * @param {HTMLElement} node
 * @param {(() => void)[]} writes
 */
function _prepareOutlookButtonWrite(node, writes) {
    writes.push(() => {
        node.before(
            createMso(`<table align="center" border="0"
                    role="presentation" cellpadding="0" cellspacing="0"
                    style="border-radius: 6px; border-collapse: separate !important;">
                        <tbody>
                            <tr>
                                <td style="${node.style.cssText
                                    .replace(RE_PADDING_MATCH, "")
                                    .replaceAll('"', "&quot;")}" ${
                                    node.parentElement.style.textAlign === "center"
                                        ? 'align="center" '
                                        : ""
                                }bgcolor="${blendColors(node.style.backgroundColor)}">
                    `),
        );
        node.after(
            createMso(`</td>
                        </tr>
                    </tbody>
                </table>`),
        );
    });
}
/**
 * @param {HTMLElement} node
 * @param {(() => void)[]} writes
 */
function _prepareElementFixupWrites(node, writes) {
    if (node.nodeName === "IMG") {
        writes.push(() => {
            if (node.classList.contains("s_media_list_img")) {
                node.style.removeProperty("height");
            }
            if (
                node.style.getPropertyValue("width") === "100%" &&
                node.style.getPropertyValue("object-fit") === ""
            ) {
                node.style.setProperty("object-fit", "cover");
            }
        });
    }
    if (node.nodeName === "TD" && !node.childNodes.length) {
        writes.push(() => {
            node.appendChild(document.createTextNode("\u00A0"));
        });
    }
    if (
        node.nodeName === "A" &&
        node.classList.contains("btn") &&
        !node.classList.contains("btn-link") &&
        !node.children.length &&
        !_isMsoComment(node.previousSibling)
    ) {
        _prepareOutlookButtonWrite(node, writes);
    } else if (
        node.nodeName === "IMG" &&
        node.classList.contains("mx-auto") &&
        node.classList.contains("d-block") &&
        !node.parentElement.classList.contains("o_outlook_hack")
    ) {
        writes.push(() => {
            _wrap(node, "p", "o_outlook_hack", "text-align:center;margin:0");
        });
    }
}
/**
 * @param {HTMLElement} node
 * @param {CssRule[]|undefined} nodeRules
 * @param {StyleMap} css
 * @param {(() => void)[]} writes
 */
function _prepareBlacklistedStyleWrite(node, nodeRules, css, writes) {
    const matchedBlacklistRules = nodeRules?.filter((rule) =>
        CONVERT_INLINE_BLACKLIST_CLASSES.some(
            (cls) => rule.selector.includes(cls) && node.classList.contains(cls),
        ),
    );

    const blacklistedStyles = _mergeStyleMaps(
        matchedBlacklistRules.map((rule) => rule.style),
    );

    const stylesToRemove = Object.fromEntries(
        Object.entries(css).filter(([key, value]) => blacklistedStyles[key] === value),
    );
    const nodeStyle = /** @type {IndexableStyle} */ (node.style);
    writes.push(() => {
        for (const [key] of Object.entries(stylesToRemove)) {
            if (nodeStyle[key]) {
                node.style.removeProperty(key);
            }
        }
    });
}
/** @param {Iterable<HTMLElement>} nodes */
function _resolveComputedStyles(nodes) {
    /** @type {(() => void)[]} */
    const computedWrites = [];
    for (const node of nodes) {
        /** @type {IndexableStyle|undefined} */
        let computedStyle;
        /** @type {[string, string][]} */
        const dynamicStyles = [];
        for (const styleName of node.style) {
            const styleValue = node.style.getPropertyValue(styleName);
            if (styleValue.includes("var(") || styleValue.includes("calc(")) {
                computedStyle =
                    computedStyle ||
                    /** @type {IndexableStyle} */ (getComputedStyle(node));
                const prop = styleValue.includes("var(")
                    ? styleValue.replace(/var\((.*)\)/, "$1")
                    : styleName;
                let value =
                    computedStyle.getPropertyValue(prop) ||
                    computedStyle.getPropertyValue(styleName);
                if (value.includes("calc(")) {
                    value = computedStyle.getPropertyValue(styleName);
                }
                dynamicStyles.push([styleName, value]);
            }
        }
        /** @type {[string, string][]} */
        const fontStyles = [];
        const propsToConvert = FONT_PROPERTIES_TO_INHERIT.filter(
            (prop) => /** @type {IndexableStyle} */ (node.style)[prop] === "inherit",
        );
        if (propsToConvert.length) {
            computedStyle =
                computedStyle || /** @type {IndexableStyle} */ (getComputedStyle(node));
            for (const prop of propsToConvert) {
                fontStyles.push([prop, computedStyle[prop]]);
            }
        }
        if (dynamicStyles.length || fontStyles.length) {
            computedWrites.push(() => {
                for (const [styleName, value] of [...dynamicStyles, ...fontStyles]) {
                    node.style.setProperty(styleName, value);
                }
            });
        }
    }
    computedWrites.forEach((fn) => fn());
}
/**
 * @param {HTMLElement} element
 * @param {CssRule[]} cssRules
 */
export function classToStyle(element, cssRules) {
    /** @type {(() => void)[]} */
    const writes = [];
    const nodeToRules = _matchRulesToNodes(element, cssRules);
    const styleProbe = document.createElement("span");

    for (const [node, nodeRules] of nodeToRules) {
        const css = nodeRules ? _getMatchedCSSRules(node, nodeRules) : {};
        _prepareStyleAttributeWrite(node, css, styleProbe, writes);
        _prepareThemeColorClassWrite(node, writes);
        _prepareElementFixupWrites(node, writes);
        _prepareBlacklistedStyleWrite(node, nodeRules, css, writes);
    }
    writes.forEach((fn) => fn());

    _resolveComputedStyles(nodeToRules.keys());
}
/** @param {Element} element */
function enforceTablesResponsivity(element) {
    const trs = [...element.querySelectorAll(".o_mail_wrapper tr")]
        .filter((tr) =>
            [...tr.children].some((td) => td.classList.contains("o_converted_col")),
        )
        .reverse();
    for (const tr of trs) {
        const commonTable = _createTable();
        commonTable.style.height = "100%";
        const commonTr = document.createElement("tr");
        const commonTd = document.createElement("td");
        _markGenerated(commonTr, commonTd);
        commonTr.appendChild(commonTd);
        commonTable.appendChild(commonTr);
        const tds = [
            .../** @type {HTMLCollectionOf<HTMLElement>} */ (tr.children),
        ].filter((child) => child.nodeName === "TD");
        let index = 0;
        for (const td of tds) {
            const width = td.style.maxWidth;
            const div = document.createElement("div");
            _markGenerated(div);
            div.style.display = "inline-block";
            div.style.verticalAlign = "top";
            div.classList.add("o_stacking_wrapper");
            commonTd.appendChild(div);
            const newTable = _createTable();
            newTable.style.width = width;
            newTable.classList.add("o_stacking_wrapper");
            div.appendChild(newTable);
            const newTr = document.createElement("tr");
            _markGenerated(newTr);
            newTable.appendChild(newTr);
            newTr.appendChild(td);
            td.style.width = "100%";
            td.removeAttribute("width");
            if (index === 0) {
                div.before(
                    createMso(`
                    <table cellpadding="0" cellspacing="0" border="0" role="presentation" style="width: 100%;">
                        <tr>
                            <td valign="top" style="width: ${width};">`),
                );
            } else {
                div.before(
                    createMso(`</td><td valign="top" style="width: ${width};">`),
                );
            }
            if (index === tds.length - 1) {
                div.after(createMso(`</td></tr></table>`));
            }
            index++;
        }
        const topTd = document.createElement("td");
        _markGenerated(topTd);
        topTd.appendChild(commonTable);
        tr.prepend(topTd);
    }
}
/**
 * Give the cells of one masonry row a shared height, and let a row that asks
 * for the full height take its share of the parent.
 *
 * @param {HTMLElement} tr
 */
function sizeMasonryRow(tr) {
    const height = _getHeight(tr);
    const tds = [.../** @type {HTMLCollectionOf<HTMLElement>} */ (tr.children)].filter(
        (child) => child.nodeName === "TD",
    );
    const tdsWithTable = tds.filter((td) =>
        [...td.children].some((child) => child.nodeName === "TABLE"),
    );
    if (tdsWithTable.length) {
        for (const tdWithTable of tdsWithTable) {
            tdWithTable.classList.add("o_desktop_h100");
            tdWithTable.style.setProperty("height", "100%");
        }
        tds.forEach((td) => td.style.setProperty("height", height + "px"));
    }
    const trSiblings = [...tr.parentElement.children].filter(
        (child) => child.nodeName === "TR",
    );
    if (
        trSiblings.length > 1 &&
        (tr.classList.contains("h-100") ||
            tr.style.getPropertyValue("height") === "100%")
    ) {
        tr.style.setProperty(
            "height",
            `${_getHeight(tr.parentElement) / trSiblings.length}px`,
        );
    }
}
/** @param {HTMLElement} tr */
function markMasonryRowFullHeight(tr) {
    const height = tr.style.height.includes("px")
        ? parseFloat(tr.style.height.replace("px", "").trim())
        : _getHeight(tr);
    tr.closest("table").classList.add("o_desktop_h100");
    tr.classList.add("o_desktop_h100");
    for (const td of [
        .../** @type {HTMLCollectionOf<HTMLElement>} */ (tr.children),
    ].filter((child) => child.nodeName === "TD")) {
        td.classList.add("o_desktop_h100");
        td.style.setProperty("height", "100%");
        const children = [...td.children];
        const childrenNames = children.map((child) => child.nodeName);
        if (
            !childrenNames.includes("TABLE") &&
            !children.some(
                (child) =>
                    child.nodeName === "DIV" && child.hasAttribute(GENERATED_ATTRIBUTE),
            )
        ) {
            const wrapper = document.createElement("div");
            _markGenerated(wrapper);
            wrapper.style.setProperty("display", "inline-block");
            wrapper.style.setProperty("width", "100%");
            const tdStyle = getComputedStyle(td);
            wrapper.style.setProperty("color", tdStyle.color);
            const firstNonCommentChild = [...td.childNodes].find(
                (child) => child.nodeType !== Node.COMMENT_NODE,
            );
            let anchor;
            if (firstNonCommentChild) {
                anchor = getAdjacentPreviousSiblings(firstNonCommentChild)
                    .filter((sib) => sib.nodeType !== Node.TEXT_NODE)
                    .shift();
            }
            for (const child of [...td.childNodes].filter(
                (child) => child.nodeType !== Node.COMMENT_NODE,
            )) {
                wrapper.append(child);
            }
            anchor ? anchor.after(wrapper) : td.append(wrapper);
            const centeringSpan = document.createElement("span");
            _markGenerated(centeringSpan);
            centeringSpan.style.setProperty("height", "100%");
            centeringSpan.style.setProperty("display", "inline-block");
            centeringSpan.style.setProperty("vertical-align", "middle");
            td.prepend(centeringSpan);
            if (td.style.height.includes("%")) {
                const newHeight =
                    (height * parseFloat(td.style.height.replace("%").trim())) / 100;
                td.style.setProperty("height", newHeight + "px");
                td.style.setProperty("max-height", newHeight + "px");
                wrapper.style.setProperty("max-height", newHeight + "px");
                const firstChild = /** @type {HTMLElement} */ (
                    wrapper.firstElementChild
                );
                if (
                    wrapper.childElementCount === 1 &&
                    firstChild.nodeName === "IMG" &&
                    firstChild.style.height === "100%"
                ) {
                    firstChild.style.setProperty("max-height", newHeight + "px");
                }
            }
        }
    }
}
/** @param {HTMLElement} element */
function handleMasonry(element) {
    const masonryTrs = element.querySelectorAll(".s_masonry_block tr");
    for (const tr of masonryTrs) {
        sizeMasonryRow(tr);
    }
    for (const tr of masonryTrs) {
        markMasonryRowFullHeight(tr);
    }
}
/** @param {Element} element */
function enforceImagesResponsivity(element) {
    for (const image of element.querySelectorAll("td > img")) {
        const td = image.parentElement;
        if (
            td.childElementCount === 1 &&
            (image.classList.contains("h-100") ||
                _getStylePropertyValue(image, "height") === "100%")
        ) {
            td.style.setProperty("height", _getHeight(td.parentElement) + "px");
            image.style.setProperty("height", "100%");
        }
    }
    for (const image of element.querySelectorAll('img[width="100%"][height]')) {
        image.before(createMso(image.outerHTML));
        image.classList.add("mso-hide");
        image.removeAttribute("height");
    }
}
/** @param {HTMLElement} element */
function pinCardImageHeights(element) {
    for (const imgTop of element.querySelectorAll(".card-img-top")) {
        imgTop.style.setProperty("height", _getHeight(imgTop) + "px");
    }
}
/** @param {HTMLElement} element */
function pinEmptyBorderedHeights(element) {
    for (const el of element.querySelectorAll(
        ".o_not_editable[class*='border-']:empty",
    )) {
        el.style.height = getComputedStyle(el).height;
    }
}
/** @param {HTMLElement} element */
function duplicateFluidImagesForOutlook(element) {
    for (const image of element.querySelectorAll("img.img-fluid")) {
        if ((image.getAttribute("style") || "").includes("mso-hide")) {
            continue;
        }
        const width = _getWidth(image);
        const clone = /** @type {HTMLImageElement} */ (image.cloneNode());
        clone.setAttribute("width", String(width));
        clone.style.setProperty("width", width + "px");
        clone.style.removeProperty("max-width");
        image.before(createMso(clone.outerHTML));
        _hideForOutlook(image);
    }
}
/** @param {HTMLElement} element */
function normalizeRemFromRoot(element) {
    const rootFontSizeProperty = getComputedStyle(
        element.ownerDocument.documentElement,
    ).fontSize;
    const rootFontSize = parseFloat(rootFontSizeProperty.replace(/[^\d.]/g, ""));
    normalizeRem(element, rootFontSize);
}
/** @param {HTMLElement} element */
function pinImageDimensions(element) {
    for (const attributeName of ["width", "height"]) {
        const images = element.querySelectorAll("img");
        for (const image of images) {
            if (/** @type {IndexableStyle} */ (image.style)[attributeName] !== "auto") {
                const value =
                    image.getAttribute(attributeName) ||
                    (attributeName === "height" && image.offsetHeight) ||
                    (attributeName === "width" ? _getWidth(image) : _getHeight(image));
                if (value) {
                    image.setAttribute(attributeName, String(value));
                    image.style.setProperty(attributeName, value + "px");
                }
            }
        }
    }
}
/** @param {HTMLElement} element */
function centreLoneImagesInCells(element) {
    for (const centeredImage of element.querySelectorAll("td > img.mx-auto")) {
        if (centeredImage.parentElement.children.length === 1) {
            centeredImage.parentElement.style.setProperty("text-align", "center");
        }
    }
}
/** @param {HTMLElement} element */
function stripContentEditable(element) {
    [element, ...element.querySelectorAll("[contenteditable]")].forEach((node) =>
        node.removeAttribute("contenteditable"),
    );
}
/** @param {HTMLElement} element */
function normalizeFontFamilyQuoting(element) {
    element
        .querySelectorAll("[style*=font-family]")
        .forEach((n) =>
            n.nodeName === "IMG"
                ? n.style.removeProperty("font-family")
                : n.setAttribute("style", n.getAttribute("style").replaceAll('"', "'")),
        );
}
/** @param {HTMLElement} element */
function stripConvertedColMarkers(element) {
    element
        .querySelectorAll(".o_converted_col")
        .forEach((node) => node.classList.remove("o_converted_col"));
}
/**
 * @param {HTMLElement} element
 * @param {CssRule[]} cssRules
 */
export async function toInline(element, cssRules) {
    await waitUntilImagesLoaded(element);
    pinCardImageHeights(element);
    pinEmptyBorderedHeights(element);
    attachmentThumbnailToLinkImg(element);
    fontToImg(element);
    await svgToPng(element);
    await webpToPng(element);
    duplicateFluidImagesForOutlook(element);
    classToStyle(element, cssRules);
    bootstrapToTable(element);
    cardToTable(element);
    listGroupToTable(element);
    addTables(element);
    handleMasonry(element);
    normalizeRemFromRoot(element);
    enforceImagesResponsivity(element);
    enforceTablesResponsivity(element);
    flattenBackgroundImages(element);
    formatTables(element);
    normalizeColors(element);
    responsiveToStaticForOutlook(element);
    pinImageDimensions(element);
    centreLoneImagesInCells(element);
    stripContentEditable(element);
    element.querySelectorAll(".mso-hide").forEach((node) => _hideForOutlook(node));
    normalizeFontFamilyQuoting(element);
    stripConvertedColMarkers(element);
}
/** @param {Element} element */
function flattenBackgroundImages(element) {
    const backgroundImages = [...element.querySelectorAll("*[style*=background-image]")]
        .filter((el) => !el.closest(".mso-hide"))
        .reverse();
    for (const backgroundImage of backgroundImages) {
        const vml = _backgroundImageToVml(backgroundImage);
        if (vml) {
            backgroundImage.after(createMso(vml));
            backgroundImage.classList.add("mso-hide");
        }
        if (backgroundImage.hasAttribute("data-bg-src")) {
            backgroundImage.removeAttribute("data-bg-src");
        }
    }
}
/**
 * @param {HTMLElement} font
 * @returns {{icon: string|undefined, content: string|undefined}}
 */
function findIconGlyph(font) {
    /** @type {string|undefined} */
    let icon;
    /** @type {string|undefined} */
    let content;
    fonts.fontIcons.find((fontIcon) =>
        fonts.getCssSelectors(fontIcon.parser, fontIcon.cssFilter).find(
            /** @param {{selector: string, names: string[], css: string}} data */
            (data) => {
                if (font.matches(data.selector.replace(/::?before/g, ""))) {
                    icon = data.names[0].split("-").shift();
                    const glyphMatch = data.css.match(
                        /(?:--fa|content):\s*(['"])((?:\\[0-9a-f]+|.)?)\1/i,
                    );
                    if (glyphMatch) {
                        content = glyphMatch[2].startsWith("\\")
                            ? String.fromCodePoint(parseInt(glyphMatch[2].slice(1), 16))
                            : glyphMatch[2];
                    }
                    return true;
                }
            },
        ),
    );
    return { icon, content };
}
/**
 * @param {HTMLElement} font
 * @returns {string}
 */
function getIconBackgroundColor(font) {
    let backgroundColoredElement = font;
    let bg, isTransparent;
    do {
        bg = _getStylePropertyValue(
            backgroundColoredElement,
            "background-color",
        ).replace(/\s/g, "");
        isTransparent = bg === "transparent" || bg === "rgba(0,0,0,0)";
        backgroundColoredElement = backgroundColoredElement.parentElement;
    } while (isTransparent && backgroundColoredElement);
    if (bg === "rgba(0,0,0,0)" && isTransparent) {
        bg = "rgb(255,255,255)";
    }
    return bg;
}
/**
 * Read the icon as authored, then let it size to its glyph so the intrinsic
 * dimensions can be measured. The style attribute is captured first on
 * purpose: the image carries what the author wrote, not "fit-content".
 *
 * @param {HTMLElement} font
 */
function measureIcon(font) {
    const style = font.getAttribute("style");
    const width = _getWidth(font);
    const height = _getHeight(font);
    const lineHeight = _getStylePropertyValue(font, "line-height");
    font.style.setProperty("height", "fit-content");
    font.style.setProperty("width", "fit-content");
    font.style.setProperty("line-height", "normal");
    return {
        style,
        width,
        height,
        lineHeight,
        intrinsicWidth: _getWidth(font),
        intrinsicHeight: _getHeight(font),
    };
}
/**
 * @param {{width: number, height: number, intrinsicWidth: number, intrinsicHeight: number}} measures
 * @returns {string}
 */
function getIconPadding({ width, height, intrinsicWidth, intrinsicHeight }) {
    const hPadding = width && intrinsicWidth && (width - intrinsicWidth) / 2;
    const vPadding = height && intrinsicHeight && (height - intrinsicHeight) / 2;
    if (!hPadding && !vPadding) {
        return "";
    }
    return (vPadding ? vPadding + "px " : "0 ") + (hPadding ? hPadding + "px" : "0");
}
/**
 * @param {HTMLElement} font
 * @param {string} icon
 * @param {string} content
 */
function replaceIconWithImage(font, icon, content) {
    const color = _getStylePropertyValue(font, "color").replace(/\s/g, "");
    const bg = getIconBackgroundColor(font);
    const { style, width, height, lineHeight, intrinsicWidth, intrinsicHeight } =
        measureIcon(font);
    const padding = getIconPadding({
        width,
        height,
        intrinsicWidth,
        intrinsicHeight,
    });
    const image = document.createElement("img");
    image.setAttribute("width", String(intrinsicWidth));
    image.setAttribute("height", String(intrinsicHeight));
    image.setAttribute(
        "src",
        `/mail/font_to_img/${content.charCodeAt(0)}/${encodeURIComponent(
            color,
        )}/${encodeURIComponent(bg)}/${Math.max(1, Math.round(intrinsicWidth))}x${Math.max(
            1,
            Math.round(intrinsicHeight),
        )}`,
    );
    image.setAttribute("data-class", font.getAttribute("class"));
    image.setAttribute("data-style", style);
    image.setAttribute("style", style);
    image.style.setProperty("box-sizing", "border-box");
    image.style.setProperty("line-height", lineHeight);
    image.style.setProperty("width", intrinsicWidth + "px");
    image.style.setProperty("height", intrinsicHeight + "px");
    image.style.setProperty("vertical-align", "unset");
    if (!padding) {
        image.style.setProperty("margin", _getStylePropertyValue(font, "margin"));
    }
    const wrapper = document.createElement("span");
    wrapper.style.setProperty("display", "inline-block");
    wrapper.append(image);
    font.before(wrapper);
    if (font.classList.contains("mx-auto")) {
        wrapper.parentElement.style.textAlign = "center";
    }
    font.remove();
    wrapper.style.setProperty("padding", padding);
    const wrapperWidth =
        width +
        ["left", "right"].reduce(
            (sum, side) =>
                sum +
                (+_getStylePropertyValue(image, `margin-${side}`).replace("px", "") ||
                    0),
            0,
        );
    wrapper.style.setProperty("width", wrapperWidth + "px");
    wrapper.style.setProperty("height", height + "px");
    wrapper.style.setProperty("vertical-align", "text-bottom");
    wrapper.style.setProperty("background-color", image.style.backgroundColor);
    wrapper.setAttribute(
        "class",
        "oe_unbreakable " +
            font
                .getAttribute("class")
                .replace(new RegExp("(^|\\s+)" + icon + "(-[^\\s]+)?", "gi"), ""),
    );
}
/**
 * @param {HTMLElement} element
 */
function fontToImg(element) {
    for (const font of element.querySelectorAll(
        ".fa, .fa-solid, .fa-regular, .fa-brands",
    )) {
        const { icon, content } = findIconGlyph(font);
        if (content) {
            replaceIconWithImage(font, icon, content);
        } else {
            font.remove();
        }
    }
}
/**
 * @param {HTMLElement} table
 * @returns {Record<string, number>}
 */
function _getTablePadding(table) {
    const read = (side) =>
        parseFloat(
            _getStylePropertyValue(table, `padding-${side}`).match(RE_PADDING)[1],
        );
    return {
        top: read("top"),
        right: read("right"),
        bottom: read("bottom"),
        left: read("left"),
    };
}
/**
 * @param {HTMLElement} column
 * @param {Record<string, number>} tablePadding
 * @param {Record<string, boolean>} atEdge
 * @param {(() => void)[]} writes
 */
function _addTablePaddingToCell(column, tablePadding, atEdge, writes) {
    const columnStyle = /** @type {IndexableStyle} */ (column.style);
    for (const [side, isAtEdge] of Object.entries(atEdge)) {
        if (!isAtEdge) {
            continue;
        }
        const match = _getStylePropertyValue(column, `padding-${side}`).match(
            RE_PADDING,
        );
        const columnPadding = match ? parseFloat(match[1]) : 0;
        writes.push(() => {
            columnStyle[`padding-${side}`] = `${columnPadding + tablePadding[side]}px`;
        });
    }
}
/** @param {HTMLElement} element */
function _moveTablePaddingToCells(element) {
    /** @type {(() => void)[]} */
    const writes = [];
    for (const table of element.querySelectorAll(
        "table.o_mail_snippet_general, .o_mail_snippet_general table",
    )) {
        const tablePadding = _getTablePadding(table);
        const rows = [...table.querySelectorAll("tr")].filter(
            (tr) => tr.closest("table") === table,
        );
        const columns = [...table.querySelectorAll("td")].filter(
            (td) => td.closest("table") === table,
        );
        for (const column of columns) {
            const columnsInRow = [
                ...column.closest("tr").querySelectorAll("td"),
            ].filter((td) => td.closest("table") === table);
            const columnIndex = columnsInRow.findIndex((col) => col === column);
            const rowIndex = rows.findIndex((row) => row === column.closest("tr"));
            _addTablePaddingToCell(
                column,
                tablePadding,
                {
                    top: !rowIndex,
                    right: columnIndex === columnsInRow.length - 1,
                    bottom: rowIndex === rows.length - 1,
                    left: !columnIndex,
                },
                writes,
            );
        }
        writes.push(() => {
            table.style.removeProperty("padding");
        });
    }
    writes.forEach((fn) => fn());
}
/** @param {HTMLElement} element */
function _addMissingTableBodies(element) {
    for (const table of [...element.querySelectorAll("table")].filter(
        (n) => ![...n.children].some((c) => c.nodeName === "TBODY"),
    )) {
        const contents = [...table.childNodes];
        const tbody = document.createElement("tbody");
        _markGenerated(tbody);
        tbody.style.setProperty("vertical-align", "top");
        table.prepend(tbody);
        tbody.append(...contents);
    }
}
/** @param {HTMLElement} element */
function _resolvePercentageHeights(element) {
    for (const node of [...element.querySelectorAll("*")].filter(
        (n) =>
            n.style &&
            n.style.getPropertyValue("height") === "100%" &&
            (!n.parentElement.style.getPropertyValue("height") ||
                n.parentElement.style.getPropertyValue("height").includes("%")),
    )) {
        let parent = node.parentElement;
        let height = parent.style.getPropertyValue("height");
        while (parent && height && height.includes("%")) {
            parent = parent.parentElement;
            height = parent.style.getPropertyValue("height");
        }
        if (parent) {
            parent.style.setProperty(
                "height",
                parent.getBoundingClientRect().height + "px",
            );
        }
    }
}
/** @param {HTMLElement} element */
function _cellAlignmentToVerticalAlign(element) {
    for (const cell of element.querySelectorAll("td")) {
        const alignSelf = cell.style.alignSelf;
        const justifyContent = cell.style.justifyContent;
        if (
            alignSelf === "start" ||
            justifyContent === "start" ||
            justifyContent === "flex-start"
        ) {
            cell.style.verticalAlign = "top";
        } else if (alignSelf === "center" || justifyContent === "center") {
            const parentCell = cell.parentElement.closest("td");
            const parentTable = cell.closest("table");
            if (parentCell) {
                parentTable.style.height = _getHeight(parentCell) + "px";
            }
            cell.style.verticalAlign = "middle";
        } else if (
            alignSelf === "end" ||
            justifyContent === "end" ||
            justifyContent === "flex-end"
        ) {
            cell.style.verticalAlign = "bottom";
        }
    }
}
/** @param {HTMLElement} element */
function _rowAlignmentToVerticalAlign(element) {
    for (const row of element.querySelectorAll("tr")) {
        const alignItems = row.style.alignItems;
        if (alignItems === "flex-start") {
            row.style.verticalAlign = "top";
        } else if (alignItems === "center") {
            row.style.verticalAlign = "middle";
        } else if (alignItems === "flex-end" || alignItems === "baseline") {
            row.style.verticalAlign = "bottom";
        } else if (alignItems === "stretch") {
            const columns = [...row.querySelectorAll("td.o_converted_col")];
            if (columns.length > 1) {
                const commonAncestor = /** @type {Element} */ (
                    commonParentGet(columns[0], columns[1])
                );
                const biggestHeight = commonAncestor.clientHeight;
                for (const column of columns) {
                    column.style.height = biggestHeight + "px";
                }
            }
        }
    }
}
/** @param {HTMLElement} element */
function _inheritTableFontProperties(element) {
    for (const table of element.querySelectorAll("table")) {
        const tableStyle = /** @type {IndexableStyle} */ (table.style);
        const propsToConvert = FONT_PROPERTIES_TO_INHERIT.filter(
            (prop) => tableStyle[prop] === "inherit" || !tableStyle[prop],
        );
        for (const prop of propsToConvert) {
            /** @type {HTMLElement} */
            let ancestor = table;
            let ancestorStyle = /** @type {IndexableStyle} */ (ancestor.style);
            while (
                ancestor &&
                (!ancestorStyle[prop] || ancestorStyle[prop] === "inherit")
            ) {
                ancestor = ancestor.parentElement;
                ancestorStyle = /** @type {IndexableStyle} */ (ancestor?.style);
            }
            if (ancestor) {
                table.style.setProperty(prop, ancestorStyle[prop]);
            }
        }
    }
}
/** @param {HTMLElement} element */
export function formatTables(element) {
    _moveTablePaddingToCells(element);
    _addMissingTableBodies(element);
    _resolvePercentageHeights(element);
    _cellAlignmentToVerticalAlign(element);
    _rowAlignmentToVerticalAlign(element);
    _inheritTableFontProperties(element);
}
/**
 * @param {Document} doc
 * @returns {CssRule[]}
 */
export function getCSSRules(doc) {
    /** @type {CssRule[]} */
    const cssRules = [];
    for (const sheet of [...doc.styleSheets, ...doc.adoptedStyleSheets]) {
        let rules;
        try {
            rules = sheet.rules || sheet.cssRules;
        } catch (e) {
            console.warn("Can't read the css rules of: " + sheet.href, e);
            continue;
        }
        _collectCSSRules(rules || [], cssRules, []);
    }

    return cssRules;
}
/**
 * @param {CSSRuleList | CSSRule[]} rules
 * @param {CssRule[]} cssRules
 * @param {string[]} parentSelectors
 */
function _collectCSSRules(rules, cssRules, parentSelectors) {
    for (const rule of rules) {
        switch (rule.constructor.name) {
            case "CSSStyleRule": {
                const styleRule = /** @type {CSSStyleRule} */ (rule);
                /** @type {string[]} */
                const selectors = [];
                for (const part of splitSelectorAroundCommasOutsideParentheses(
                    styleRule.selectorText || "",
                )) {
                    const selector = part.trim();
                    if (!selector) {
                        continue;
                    }
                    if (!parentSelectors.length) {
                        selectors.push(selector);
                    } else if (selector.includes("&")) {
                        for (const parentSelector of parentSelectors) {
                            selectors.push(selector.replaceAll("&", parentSelector));
                        }
                    } else {
                        for (const parentSelector of parentSelectors) {
                            selectors.push(`${parentSelector} ${selector}`);
                        }
                    }
                }
                const keptSelectors = selectors.filter(
                    (selector) => !SELECTORS_IGNORE.test(selector),
                );
                for (const selector of keptSelectors) {
                    cssRules.push({ selector, rawRule: styleRule });
                    if (selector === "body") {
                        cssRules.push({
                            selector: ".o_layout",
                            rawRule: styleRule,
                            specificity: 1,
                        });
                    }
                }
                if (styleRule.cssRules?.length && keptSelectors.length) {
                    _collectCSSRules(styleRule.cssRules, cssRules, keptSelectors);
                }
                break;
            }
            case "CSSMediaRule": {
                const mediaRule = /** @type {CSSMediaRule} */ (rule);
                if (_isMediaConditionInlineable(mediaRule.conditionText)) {
                    _collectCSSRules(mediaRule.cssRules, cssRules, parentSelectors);
                }
                break;
            }
            case "CSSSupportsRule": {
                const supportsRule = /** @type {CSSSupportsRule} */ (rule);
                let supported = false;
                try {
                    supported = CSS.supports(supportsRule.conditionText);
                } catch {}
                if (supported) {
                    _collectCSSRules(supportsRule.cssRules, cssRules, parentSelectors);
                }
                break;
            }
            case "CSSLayerBlockRule": {
                const layerRule = /** @type {CSSGroupingRule} */ (rule);
                _collectCSSRules(layerRule.cssRules, cssRules, parentSelectors);
                break;
            }
            case "CSSNestedDeclarations": {
                const nestedRule = /** @type {CSSStyleRule} */ (rule);
                for (const selector of parentSelectors) {
                    cssRules.push({ selector, rawRule: nestedRule });
                }
                break;
            }
        }
    }
}
/**
 * @param {string} conditionText
 * @returns {boolean}
 */
function _isMediaConditionInlineable(conditionText) {
    const condition = (conditionText || "").trim();
    if (!condition || /^(all|screen)$/i.test(condition)) {
        return true;
    }
    if (/\bprint\b/i.test(condition) || /max-width/i.test(condition)) {
        return false;
    }
    const minWidthMatch = condition.match(/\(\s*min-width\s*:\s*(\d+)/i);
    return Boolean(minWidthMatch) && +minWidthMatch[1] >= 768;
}
/** @param {Element} element */
export function listGroupToTable(element) {
    for (const listGroup of element.querySelectorAll(".list-group")) {
        /** @type {Element} */
        let table;
        if (listGroup.querySelectorAll(".list-group-item").length) {
            table = _createTable(listGroup.attributes);
        } else {
            table = /** @type {Element} */ (listGroup.cloneNode());
            for (const attr of listGroup.attributes) {
                table.setAttribute(attr.name, attr.value);
            }
        }
        for (const child of [...listGroup.childNodes]) {
            const childElement = /** @type {Element} */ (child);
            if (
                childElement.classList &&
                childElement.classList.contains("list-group-item")
            ) {
                const row = document.createElement("tr");
                const col = document.createElement("td");
                _markGenerated(row, col);
                for (const attr of childElement.attributes) {
                    col.setAttribute(attr.name, attr.value);
                }
                col.append(...child.childNodes);
                col.classList.remove("list-group-item");
                if (!col.className) {
                    col.removeAttribute("class");
                }
                row.append(col);
                table.append(row);
                child.remove();
            } else if (child.nodeName === "LI") {
                table.append(...child.childNodes);
            } else {
                table.append(child);
            }
        }
        table.classList.remove("list-group");
        if (!table.className) {
            table.removeAttribute("class");
        }
        if (listGroup.nodeName === "TD") {
            listGroup.append(table);
            listGroup.classList.remove("list-group");
            if (!listGroup.className) {
                listGroup.removeAttribute("class");
            }
        } else {
            listGroup.before(table);
            listGroup.remove();
        }
    }
}
/** @param {HTMLElement} element */
export function normalizeColors(element) {
    for (const node of element.querySelectorAll('[style*="rgb"]')) {
        const rgbaMatch = node
            .getAttribute("style")
            .match(/rgba?\(([\d.]+\s*,?\s*){3,4}\)/g);
        for (const rgb of rgbaMatch || []) {
            node.setAttribute(
                "style",
                node.getAttribute("style").replace(rgb, blendColors(rgb, node)),
            );
        }
    }
}
/**
 * @param {HTMLElement} element
 * @param {Number} rootFontSize=16
 */
export function normalizeRem(element, rootFontSize = 16) {
    for (const node of element.querySelectorAll('[style*="rem"]')) {
        const remMatch = node.getAttribute("style").match(/[\d.]+\s*rem/g);
        for (const rem of remMatch || []) {
            const remValue = parseFloat(rem.replace(/[^\d.]/g, ""));
            const pxValue = Math.round(remValue * rootFontSize * 100) / 100;
            node.setAttribute(
                "style",
                node.getAttribute("style").replace(rem, pxValue + "px"),
            );
        }
    }
}

/** @param {Element} element */
function responsiveToStaticForOutlook(element) {
    for (const td of element.querySelectorAll("td.o_converted_col:not(.mso-hide)")) {
        const tdStyle = td.getAttribute("style") || "";
        const msoAttributes = [...td.attributes].filter(
            (attr) => attr.name !== "style" && attr.name !== "width",
        );
        const msoWidth = td.style.getPropertyValue("max-width");
        const msoStyles = tdStyle.replace(/(^| |max-)width:[^;]*;\s*/g, "");
        const outlookTd = document.createElement("td");
        for (const attribute of msoAttributes) {
            outlookTd.setAttribute(attribute.name, td.getAttribute(attribute.name));
        }
        if (msoWidth) {
            outlookTd.setAttribute("width", ("" + msoWidth).replace("px", "").trim());
            outlookTd.setAttribute("style", `${msoStyles}width: ${msoWidth};`);
        } else {
            outlookTd.setAttribute("style", msoStyles);
        }
        if (td.closest(".s_masonry_block")) {
            outlookTd.style.padding = "0";
        }
        if (td.children.length === 1 && td.firstElementChild.nodeName === "IMG") {
            const tdComputedStyle = /** @type {IndexableStyle} */ (
                getComputedStyle(td)
            );
            const imageStyle = /** @type {IndexableStyle} */ (
                /** @type {HTMLElement} */ (td.firstElementChild).style
            );
            const outlookTdStyle = /** @type {IndexableStyle} */ (outlookTd.style);
            for (const side of ["left", "right"]) {
                if (imageStyle.width === "100%") {
                    const prop = `padding-${side}`;
                    const imagePadding = +imageStyle[prop].replace("px", "");
                    if (imagePadding > 0) {
                        const tdPadding = +tdComputedStyle[prop].replace("px", "") || 0;
                        outlookTdStyle[prop] = tdPadding + imagePadding + "px";
                    }
                }
            }
        }
        td.before(createMso(outlookTd.outerHTML.replace("</td>", "")));
        _hideForOutlook(td, "opening");
    }
}
/** @param {HTMLImageElement} source */
async function convertToPng(source) {
    await new Promise((resolve) => {
        source.onload = () => resolve();
        source.onerror = () => resolve();
        if (source.complete) {
            resolve();
        }
    });
    if (!source.naturalWidth || !source.naturalHeight) {
        return;
    }
    const image = document.createElement("img");
    const canvas = document.createElement("canvas");
    const width = _getWidth(source);
    const height = _getHeight(source);

    canvas.setAttribute("width", String(width));
    canvas.setAttribute("height", String(height));
    let png;
    try {
        canvas.getContext("2d").drawImage(source, 0, 0, width, height);
        png = canvas.toDataURL("image/png");
    } catch {
        return;
    }

    for (const attribute of source.attributes) {
        image.setAttribute(attribute.name, attribute.value);
    }

    image.setAttribute("src", png);
    image.setAttribute("width", String(width));
    image.setAttribute("height", String(height));

    source.before(image);
    source.remove();
}

/**
 * @param {HTMLElement} element
 */
async function svgToPng(element) {
    for (const svg of /** @type {NodeListOf<HTMLImageElement>} */ (
        element.querySelectorAll('img[src*=".svg"]')
    )) {
        await convertToPng(svg);
    }
}

/**
 * @param {HTMLElement} element
 */
async function webpToPng(element) {
    for (const webp of /** @type {NodeListOf<HTMLImageElement>} */ (
        element.querySelectorAll('img[src*=".webp"]')
    )) {
        await convertToPng(webp);
    }
}

/**
 * @param {HTMLElement} element
 * @param {number} colspan
 * @param {number} tableWidth
 */
function _applyColspan(element, colspan, tableWidth) {
    element.setAttribute("colspan", String(colspan));
    const widthPercentage = +element.getAttribute("colspan") / 12;
    const width = Math.round(tableWidth * widthPercentage * 100) / 100;
    element.style.setProperty("max-width", width + "px");
    element.classList.add("o_converted_col");
}
/**
 * @param {HTMLElement} backgroundImage
 * @returns {string}
 */
function _backgroundImageToVml(backgroundImage) {
    const matches = backgroundImage.style.backgroundImage.match(/url\("?(.+?)"?\)/);
    const url = matches && matches[1];
    if (url) {
        const clone = /** @type {HTMLElement} */ (backgroundImage.cloneNode(true));
        const div = document.createElement("div");
        div.replaceChildren(...clone.childNodes);
        const divStyle = /** @type {IndexableStyle} */ (div.style);
        /** @type {[string, string][]} */ ([
            ["fontSize", "0"],
            ["height", "100%"],
            ["width", "100%"],
        ]).forEach(([k, v]) => (divStyle[k] = v));
        const vmlContent = document.createElement("div");
        vmlContent.append(div);

        const style = /** @type {IndexableStyle} */ (getComputedStyle(backgroundImage));
        const backgroundImageStyle = /** @type {IndexableStyle} */ (
            backgroundImage.style
        );
        for (const prop of FONT_PROPERTIES_TO_INHERIT) {
            divStyle[prop] = backgroundImageStyle[prop] || style[prop];
        }
        [.../** @type {HTMLCollectionOf<HTMLElement>} */ (div.children)].forEach(
            (child) =>
                child.style.setProperty(
                    "font-size",
                    child.style.fontSize || style.fontSize,
                ),
        );

        for (const prop of [
            "background",
            "background-image",
            "background-repeat",
            "background-size",
        ]) {
            clone.style.removeProperty(prop);
        }
        clone.style.padding = "0";
        clone.className = clone.className.replace(/p[bt]\d+/g, "");
        clone.setAttribute("background", url);
        clone.setAttribute("valign", "middle");

        const [width, height] = [
            _getWidth(backgroundImage),
            _getHeight(backgroundImage),
        ];
        const vml =
            `<v:image xmlns:v="urn:schemas-microsoft-com:vml" fill="true" stroke="false" ` +
            `style="border: 0; display: inline-block; width: ${width}px; height: ${height}px;" src="${url}"/>
        <v:rect xmlns:v="urn:schemas-microsoft-com:vml" fill="true" stroke="false" ` +
            `style="border: 0; display: inline-block; position: absolute; width:${width}px; height:${height}px; v-text-anchor:middle;">
            <v:fill opacity="0%" color="#000000"/>
            <v:textbox inset="0,0,0,0">
                <table border="0" cellpadding="0" cellspacing="0">
                    <tr>
                        <td width="${width}" align="center" style="text-align: center;">${vmlContent.outerHTML}</td>
                    </tr>
                </table>
            </v:textbox>
        </v:rect>`;

        return `${clone.outerHTML.replace(
            /<\/[\w-]+>[\s\n]*$/,
            "",
        )}${vml}</${clone.nodeName.toLowerCase()}>`;
    }
}
/** @returns {HTMLTableCellElement[]} */
function _createColumnGrid() {
    return new Array(12).fill().map(() => {
        const cell = document.createElement("td");
        _markGenerated(cell);
        return cell;
    });
}
/**
 * @param {Node} [node]
 * @returns {boolean}
 */
function _isMsoComment(node) {
    return (
        node?.nodeType === Node.COMMENT_NODE && node.nodeValue.startsWith("[if mso]")
    );
}
/** @param {...Element} elements */
function _markGenerated(...elements) {
    for (const element of elements) {
        element.setAttribute(GENERATED_ATTRIBUTE, "1");
    }
}
/**
 * @param {string} content
 * @returns {Comment}
 */
export function createMso(content = "") {
    const showRegex = /<!--\[if\s+mso\]>([\s\S]*?)<!\[endif\]-->/g;
    const hideRegex = /<!--\[if\s+!mso\]>([\s\S]*?)<!\[endif\]-->/g;
    let contentToInsert = content;
    contentToInsert = contentToInsert.replace(
        showRegex,
        /**
         * @param {string} matchedContent
         * @param {string} group
         */
        (matchedContent, group) => group,
    );
    contentToInsert = contentToInsert.replace(hideRegex, "");
    return document.createComment(`[if mso]>${contentToInsert}<![endif]`);
}
/**
 * @param {NamedNodeMap | Attr[]} [attributes]
 * @returns {HTMLTableElement}
 */
function _createTable(attributes = []) {
    const table = document.createElement("table");
    _markGenerated(table);
    Object.entries(TABLE_ATTRIBUTES).forEach(([att, value]) =>
        table.setAttribute(att, String(value)),
    );
    for (const attr of attributes) {
        if (!(attr.name === "width" && attr.value === "100%")) {
            table.setAttribute(attr.name, attr.value);
        }
    }
    table.style.setProperty("width", "100%", "important");
    const tableStyle = /** @type {IndexableStyle} */ (table.style);
    if (table.classList.contains("o_layout")) {
        const layoutStyles = { ...TABLE_STYLES };
        delete layoutStyles["font-size"];
        delete layoutStyles["line-height"];
        Object.entries(layoutStyles).forEach(
            ([att, value]) => (tableStyle[att] = value),
        );
    } else {
        const namedAttributes = /** @type {Record<string, Attr>} */ (
            /** @type {unknown} */ (attributes)
        );
        for (const styleName in TABLE_STYLES) {
            if (!(
                "style" in attributes &&
                namedAttributes.style.value.includes(styleName + ":")
            )) {
                tableStyle[styleName] = TABLE_STYLES[styleName];
            }
        }
    }
    return table;
}
/**
 * @param {Element} column
 * @returns {number}
 */
function _getColumnSize(column) {
    let colMatch = column.className.match(RE_COL_MD_MATCH);
    if (!colMatch) {
        colMatch = column.className.match(RE_COL_MATCH);
    }
    const colOptions = colMatch[2] && colMatch[2].substr(1).split("-");
    const colSize =
        (colOptions && (colOptions.length === 2 ? +colOptions[1] : +colOptions[0])) ||
        0;
    return colSize;
}
/**
 * @param {Element} column
 * @returns {number}
 */
function _getColumnOffsetSize(column) {
    let offsetMatch = column.className.match(RE_OFFSET_MD_MATCH);
    if (!offsetMatch) {
        offsetMatch = column.className.match(RE_OFFSET_MATCH);
    }
    const offsetOptions =
        offsetMatch && offsetMatch[2] && offsetMatch[2].substr(1).split("-");
    const offsetSize =
        (offsetOptions &&
            (offsetOptions.length === 2 ? +offsetOptions[1] : +offsetOptions[0])) ||
        0;
    return offsetSize;
}
/**
 * @param {StyleMap[]} styleMaps
 * @returns {StyleMap}
 */
function _mergeStyleMaps(styleMaps) {
    /** @type {StyleMap} */
    const merged = {};
    for (const style of styleMaps) {
        for (const [key, value] of Object.entries(style)) {
            if (
                !merged[key] ||
                !merged[key].includes("important") ||
                value.includes("important")
            ) {
                merged[key] = value;
            }
        }
    }
    for (const [key, value] of Object.entries(merged)) {
        if (value && value.endsWith("important")) {
            merged[key] = value.replace(/\s*!important\s*$/, "");
        }
    }
    return merged;
}
/**
 * @param {HTMLElement} node
 * @param {CssRule[]} cssRules
 * @param {StyleMap} processedStyle
 */
function _resolveGroupedDynamicStyles(node, cssRules, processedStyle) {
    let computedStyle;
    for (const groupName in GROUPED_STYLES) {
        const groupProperties = [
            ...GROUPED_STYLES_SHORTHANDS[groupName],
            ...GROUPED_STYLES[groupName],
        ];
        const hasDynamicValue = cssRules.some((rule) =>
            groupProperties.some((property) => {
                const value = rule.rawRule?.style?.getPropertyValue(property);
                return value && (value.includes("var(") || value.includes("calc("));
            }),
        );
        if (!hasDynamicValue) {
            continue;
        }
        computedStyle = computedStyle || getComputedStyle(node);
        for (const styleName of GROUPED_STYLES[groupName]) {
            const styleValue = computedStyle.getPropertyValue(styleName);
            if (
                styleValue &&
                !STYLE_INITIAL_VALUES.includes(styleValue) &&
                !(styleName in processedStyle)
            ) {
                processedStyle[styleName] = styleValue;
            }
        }
    }
}
/** @param {StyleMap} processedStyle */
function _collapsePositionalShorthands(processedStyle) {
    for (const info of [
        { name: "margin" },
        { name: "padding" },
        { name: "border", suffix: "-style", defaultValue: "none" },
    ]) {
        const positions = ["top", "right", "bottom", "left"];
        const positionalKeys = positions.map(
            (position) => `${info.name}-${position}${info.suffix || ""}`,
        );
        const styles = positionalKeys
            .map((key) => processedStyle[key])
            .filter((s) => s);
        const hasVariableStyle = styles.some(
            (style) => style.includes("calc(") || style.includes("var("),
        );
        const inherits = positionalKeys.some((key) =>
            ["inherit", "initial"].includes((processedStyle[key] || "").trim()),
        );
        if (styles.length && !hasVariableStyle && !inherits) {
            const propertyName = `${info.name}${info.suffix || ""}`;
            processedStyle[propertyName] = positionalKeys.every(
                (key) => processedStyle[positionalKeys[0]] === processedStyle[key],
            )
                ? (processedStyle[propertyName] = processedStyle[positionalKeys[0]])
                : positionalKeys
                      .map((key) => processedStyle[key] || info.defaultValue || 0)
                      .join(" ");
            for (const prop of positionalKeys) {
                delete processedStyle[prop];
            }
        }
    }

    const borderRadiusKeys = GROUPED_STYLES["border-radius"];
    if (borderRadiusKeys.some((key) => processedStyle[key])) {
        const values = borderRadiusKeys.map((key) => processedStyle[key] || "0");
        processedStyle["border-radius"] = values.every((v) => v === values[0])
            ? values[0]
            : values.join(" ");
        for (const key of borderRadiusKeys) {
            delete processedStyle[key];
        }
    }
}
/** @param {StyleMap} processedStyle */
function _dropUnusableDeclarations(processedStyle) {
    for (const styleName in processedStyle) {
        if (styleName.includes("border") && processedStyle[styleName] === "initial") {
            delete processedStyle[styleName];
        }
    }

    if (processedStyle["text-decoration-line"]) {
        processedStyle["text-decoration"] = processedStyle["text-decoration-line"];
        delete processedStyle["text-decoration-line"];
        delete processedStyle["text-decoration-color"];
        delete processedStyle["text-decoration-style"];
        delete processedStyle["text-decoration-thickness"];
    }

    for (const styleName in processedStyle) {
        if (isDroppedFlexDeclaration(styleName, `${processedStyle[styleName]}`)) {
            delete processedStyle[styleName];
        }
    }
}
/**
 * @param {HTMLElement} node
 * @param {CssRule[]} cssRules
 * @returns {StyleMap}
 */
function _getMatchedCSSRules(node, cssRules) {
    const legacyNode = /** @type {Record<string, typeof node.matches>} */ (
        /** @type {unknown} */ (node)
    );
    node.matches =
        node.matches ||
        legacyNode.webkitMatchesSelector ||
        legacyNode.mozMatchesSelector ||
        legacyNode.msMatchesSelector ||
        legacyNode.oMatchesSelector;

    const styles = cssRules
        .map((rule) => removeBlacklistedStyles(rule, node))
        .filter(Boolean);

    if (node.style.length) {
        /** @type {StyleMap} */
        const inlineStyles = {};
        for (const styleName of node.style) {
            inlineStyles[styleName] = node.style.getPropertyValue(styleName);
        }
        styles.push(inlineStyles);
    }

    const processedStyle = _mergeStyleMaps(styles);
    _resolveGroupedDynamicStyles(node, cssRules, processedStyle);

    if (
        processedStyle.display === "block" &&
        !(node.classList && node.classList.contains("oe-nested"))
    ) {
        delete processedStyle.display;
    }
    if (!processedStyle["box-sizing"]) {
        processedStyle["box-sizing"] = "border-box";
    }

    _collapsePositionalShorthands(processedStyle);
    _dropUnusableDeclarations(processedStyle);

    return processedStyle;
}
/** @type {HTMLElement|undefined} */
let lastComputedStyleElement;
/** @type {IndexableStyle|undefined} */
let lastComputedStyle;
/**
 * @param {HTMLElement} element
 * @param {string} propertyName
 * @returns {string}
 */
function _getStylePropertyValue(element, propertyName) {
    const computedStyle =
        lastComputedStyleElement === element
            ? lastComputedStyle
            : /** @type {IndexableStyle} */ (getComputedStyle(element));
    lastComputedStyleElement = element;
    lastComputedStyle = computedStyle;
    return computedStyle[propertyName] || element.style.getPropertyValue(propertyName);
}
/**
 * @param {Element} element
 * @returns {Number}
 */
function _getWidth(element) {
    return parseFloat(getComputedStyle(element).width.replace("px", "")) || 0;
}
/**
 * @param {Element} element
 * @returns {Number}
 */
function _getHeight(element) {
    return parseFloat(getComputedStyle(element).height.replace("px", "")) || 0;
}
/**
 * @param {Element} node
 * @param {false|'opening'|'closing'} [onlyHideTag=false]
 */
function _hideForOutlook(node, onlyHideTag = false) {
    if (!onlyHideTag) {
        let style = (node.getAttribute("style") || "").trim();
        if (!style.includes("mso-hide")) {
            if (style && !style.endsWith(";")) {
                style += ";";
            }
            node.setAttribute("style", `${style} mso-hide: all;`);
        }
    }
    /**
     * @param {Node|null} sibling
     * @param {string} value
     */
    const isComment = (sibling, value) =>
        sibling?.nodeType === Node.COMMENT_NODE && sibling.nodeValue === value;
    if (
        !isComment(
            onlyHideTag === "closing" ? node.lastChild : node.previousSibling,
            "[if !mso]><!",
        )
    ) {
        node[onlyHideTag === "closing" ? "append" : "before"](
            document.createComment("[if !mso]><!"),
        );
    }
    if (
        !isComment(
            onlyHideTag === "opening" ? node.firstChild : node.nextSibling,
            "<![endif]",
        )
    ) {
        node[onlyHideTag === "opening" ? "prepend" : "after"](
            document.createComment("<![endif]"),
        );
    }
}
/**
 * @param {Element} element
 * @param {string} wrapperTag
 * @param {string} [wrapperClass]
 * @param {string} [wrapperStyle]
 * @returns {HTMLElement}
 */
function _wrap(element, wrapperTag, wrapperClass, wrapperStyle) {
    const wrapper = document.createElement(wrapperTag);
    _markGenerated(wrapper);
    if (wrapperClass) {
        wrapper.className = wrapperClass;
    }
    if (wrapperStyle) {
        wrapper.style.cssText = wrapperStyle;
    }
    element.parentElement.insertBefore(wrapper, element);
    wrapper.append(element);
    return wrapper;
}

const TABLE_TAGS = ["table", "thead", "tbody", "tfoot", "tr", "td", "th"];
const TABLE_TAG_SELECTOR_RE = new RegExp(
    String.raw`(^|[\s>+~,(])(${TABLE_TAGS.join("|")})(?![\w-])`,
    "i",
);
/**
 * @param {Element} node
 * @param {string} selector
 * @param {string} key
 * @returns {boolean}
 */
function isBlacklistedStyle(node, selector, key) {
    return (
        node.matches(TABLE_TAGS.join(", ")) &&
        TABLE_TAG_SELECTOR_RE.test(selector) &&
        key.includes("color")
    );
}

/**
 * @param {CssRule} rule
 * @param {Element} node
 * @returns {StyleMap}
 */
function removeBlacklistedStyles(rule, node) {
    if (!rule.style) {
        return rule.style;
    }
    /** @type {StyleMap} */
    const styles = {};
    for (const [key, value] of Object.entries(rule.style)) {
        if (isBlacklistedStyle(node, rule.selector, key)) {
            continue;
        }
        styles[key] = value;
    }
    return styles;
}

/**
 * @param {string} style
 * @returns {string}
 */
function correctBorderAttributes(style) {
    const stylesObject = style
        .replace(/\s+/g, " ")
        .split(";")
        .reduce((styles, styleString) => {
            const [attribute, value] = styleString.split(":").map((str) => str.trim());
            if (attribute) {
                styles[attribute] = value;
            }
            return styles;
        }, /** @type {StyleMap} */ ({}));

    const BORDER_WIDTHS_ATTRIBUTES = [
        "border-bottom-width",
        "border-left-width",
        "border-right-width",
        "border-top-width",
    ];

    const isBorderStyleApplied = BORDER_WIDTHS_ATTRIBUTES.some(
        (attribute) => attribute in stylesObject,
    );

    if (!isBorderStyleApplied) {
        return style;
    }

    const totalBorderWidth = BORDER_WIDTHS_ATTRIBUTES.reduce(
        (totalWidth, attribute) => {
            const widthValue = stylesObject[attribute] || "0px";
            const numericWidth = parseFloat(widthValue.replace("px", "")) || 0;
            return totalWidth + numericWidth;
        },
        0,
    );

    if (totalBorderWidth === 0) {
        let correctedStyle = style.trim();
        if (correctedStyle.slice(-1) !== ";") {
            correctedStyle += ";";
        }
        correctedStyle = correctedStyle.replace(
            /(;|^)\s*border-style\s*:[^;]*(;|$)|$/,
            "$1border-style:none$2",
        );
        return correctedStyle;
    }

    if (/border-style\s*:/i.test(style)) {
        return style;
    }
    return style.trim().replace(/;?$/, "; border-style: solid;");
}

/**
 * @param {Element} root
 * @returns {Promise<any[]>}
 */
function waitUntilImagesLoaded(root) {
    const promises = [];
    for (const img of root.querySelectorAll('img[src]:not([src=""])')) {
        const src = getImageSrc(img);
        if (src) {
            promises.push(loadImage(src));
        }
    }
    return Promise.allSettled(promises);
}
