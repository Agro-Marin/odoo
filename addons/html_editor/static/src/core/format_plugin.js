/** @odoo-module native */
import { isHtmlContentSupported } from "@html_editor/core/selection_plugin";
import { prepareUpdate } from "@html_editor/utils/dom_state";
import { withSequence } from "@html_editor/utils/resource";
import { callbacksForCursorUpdate } from "@html_editor/utils/selection";
import { _t } from "@web/core/translation";

import { Plugin } from "../plugin.js";
import { closestBlock, isBlock } from "../utils/blocks.js";
import {
    cleanTextNode,
    fillEmpty,
    removeClass,
    splitTextNode,
    unwrapContents,
} from "../utils/dom.js";
import {
    areSimilarElements,
    isContentEditable,
    isContentEditableAncestor,
    isElement,
    isEmpty,
    isEmptyTextNode,
    isPhrasingContent,
    isSelfClosingElement,
    isTextNode,
    isVisibleTextNode,
    isZwnbsp,
    isZWS,
    previousLeaf,
    PROTECTED_QWEB_SELECTOR,
} from "../utils/dom_info.js";
import { isFakeLineBreak } from "../utils/dom_state.js";
import {
    childNodes,
    closestElement,
    descendants,
    selectElements,
} from "../utils/dom_traversal.js";
import { formatsSpecs, FORMATTABLE_TAGS } from "../utils/formatting.js";
import { boundariesOut, leftPos, rightPos } from "../utils/position.js";

const allWhitespaceRegex = /^[\s\u200b]*$/;

function isFormatted(formatPlugin, format) {
    return (sel, nodes) =>
        formatPlugin.activeFormats[format]?.applyStyle ??
        formatPlugin.isSelectionFormat(format, nodes);
}

/**
 * @typedef {Object} FormatShared
 * @property { FormatPlugin['isSelectionFormat'] } isSelectionFormat
 * @property { FormatPlugin['getOrCreateZws'] } getOrCreateZws
 * @property { FormatPlugin['mergeAdjacentInlines'] } mergeAdjacentInlines
 * @property { FormatPlugin['formatSelection'] } formatSelection
 * @property { FormatPlugin['requestFormat'] } requestFormat
 */

/**
 * @typedef {((formatName: string, options: {
 * formatProps: object,
 * applyStyle: boolean,
 * }) => void | boolean)[]} format_selection_handlers
 * @typedef {(() => void)[]} remove_all_formats_handlers
 * @typedef {((className: string) => boolean)[]} format_class_predicates
 * @typedef {((node: Node) => boolean)[]} has_format_predicates
 */

export class FormatPlugin extends Plugin {
    static id = "format";
    static dependencies = ["selection", "history", "input", "split"];
    static shared = [
        "isSelectionFormat",
        "getOrCreateZws",
        "mergeAdjacentInlines",
        // `formatSelection` stays shared alongside `requestFormat`: it is what
        // addons/website's highlight plugin calls, and that is out of module.
        "formatSelection",
        "requestFormat",
    ];
    /** @type {import("plugins").EditorResources} */
    resources = {
        user_commands: [
            {
                id: "formatBold",
                description: _t("Toggle bold"),
                icon: "fa-bold",
                run: this.requestFormat.bind(this, "bold"),
                isAvailable: isHtmlContentSupported,
            },
            {
                id: "formatItalic",
                description: _t("Toggle italic"),
                icon: "fa-italic",
                run: this.requestFormat.bind(this, "italic"),
                isAvailable: isHtmlContentSupported,
            },
            {
                id: "formatUnderline",
                description: _t("Toggle underline"),
                icon: "fa-underline",
                run: this.requestFormat.bind(this, "underline"),
                isAvailable: isHtmlContentSupported,
            },
            {
                id: "formatStrikethrough",
                description: _t("Toggle strikethrough"),
                icon: "fa-strikethrough",
                run: this.requestFormat.bind(this, "strikeThrough"),
                isAvailable: isHtmlContentSupported,
            },
            {
                id: "formatFontSize",
                run: ({ size }) =>
                    this.requestFormat("fontSize", {
                        applyStyle: true,
                        formatProps: { size },
                    }),
                isAvailable: isHtmlContentSupported,
            },
            {
                id: "formatFontSizeClassName",
                run: ({ className }) =>
                    this.requestFormat("setFontSizeClassName", {
                        applyStyle: true,
                        formatProps: { className },
                    }),
                isAvailable: isHtmlContentSupported,
            },
            {
                id: "removeFormat",
                description: (sel, nodes) =>
                    nodes && this.hasAnyFormat(nodes)
                        ? _t("Remove Format")
                        : _t("Selection has no format"),
                icon: "fa-eraser",
                run: this.removeAllFormats.bind(this),
                isAvailable: isHtmlContentSupported,
            },
        ],
        shortcuts: [
            { hotkey: "control+b", commandId: "formatBold" },
            { hotkey: "control+i", commandId: "formatItalic" },
            { hotkey: "control+u", commandId: "formatUnderline" },
            { hotkey: "control+5", commandId: "formatStrikethrough" },
            { hotkey: "control+space", commandId: "removeFormat" },
        ],
        toolbar_groups: withSequence(20, { id: "decoration" }),
        toolbar_items: [
            {
                id: "bold",
                groupId: "decoration",
                namespaces: ["compact", "expanded"],
                commandId: "formatBold",
                isActive: isFormatted(this, "bold"),
            },
            {
                id: "italic",
                groupId: "decoration",
                namespaces: ["compact", "expanded"],
                commandId: "formatItalic",
                isActive: isFormatted(this, "italic"),
            },
            {
                id: "underline",
                groupId: "decoration",
                namespaces: ["compact", "expanded"],
                commandId: "formatUnderline",
                isActive: isFormatted(this, "underline"),
            },
            {
                id: "strikethrough",
                groupId: "decoration",
                commandId: "formatStrikethrough",
                isActive: isFormatted(this, "strikeThrough"),
            },
            withSequence(20, {
                id: "remove_format",
                groupId: "decoration",
                commandId: "removeFormat",
                isDisabled: (sel, nodes) => !this.hasAnyFormat(nodes),
            }),
        ],
        beforeinput_handlers: withSequence(20, this.onBeforeInput.bind(this)),
        clean_for_save_handlers: this.cleanForSave.bind(this),
        normalize_handlers: this.normalize.bind(this),
        selectionchange_handlers: this.clearPendingFormats.bind(this),
        before_set_tag_handlers: this.removeFontSizeFormat.bind(this),
        before_insert_handlers: this.beforeInsert.bind(this),
        delete_handlers: this.convertEmptyFormatToPendingIntent.bind(this),

        intangible_char_for_keyboard_navigation_predicates: (_, char) =>
            char === "\u200b",
    };

    setup() {
        /**
         * Format intents recorded on a collapsed selection and not yet written
         * to the DOM, keyed by format name.
         */
        this.activeFormats = {};
    }

    /**
     * @param {string[]} formats
     * @param {Node[]} targetedNodes
     */
    removeFormats(formats, targetedNodes) {
        const editableTargetedNodes = targetedNodes.filter(
            this.dependencies.selection.isNodeEditable,
        );
        for (const format of formats) {
            if (
                !formatsSpecs[format].removeStyle ||
                !this.hasSelectionFormat(format, editableTargetedNodes)
            ) {
                continue;
            }
            this.formatSelection(format, { applyStyle: false, removeFormat: true });
        }
    }

    /**
     * When a delete leaves the caret inside an empty styled inline, turn that
     * inline back into a pending intent so the format survives for the next
     * character typed.
     */
    convertEmptyFormatToPendingIntent() {
        const selection = this.dependencies.selection.getEditableSelection();
        const anchorNode = selection.anchorNode;
        let element = closestElement(anchorNode);
        if (!isZWS(element) || !isPhrasingContent(element)) {
            return;
        }
        const cursor = this.dependencies.selection.preserveSelection();
        while (
            (isZWS(element) || isEmpty(element)) &&
            isPhrasingContent(element) &&
            !this.isUnremovable(element)
        ) {
            const format = Object.keys(formatsSpecs).find((formatName) => {
                const spec = formatsSpecs[formatName];
                return spec.isTag?.(element) || spec.hasStyle?.(element);
            });
            if (!format) {
                break;
            }
            const parent = element.parentElement;
            const restore = prepareUpdate(
                ...leftPos(anchorNode),
                ...rightPos(anchorNode),
            );
            removeFormat(element, formatsSpecs[format], cursor);
            this.activeFormats[format] = { applyStyle: true };
            if (
                element.isConnected &&
                element.getAttributeNames().length === 1 &&
                element.hasAttribute("data-oe-zws-empty-inline")
            ) {
                cursor.update(callbacksForCursorUpdate.remove(element));
                element.remove();
            }
            restore();
            element = parent;
            // A delete also fires a selectionchange, which would normally
            // discard pending intents. We have just recorded one, so skip the
            // next clear (see clearPendingFormats).
            this.skipNextFormatClear = true;
        }
        cursor.restore();
    }

    /**
     * @param {Node} node
     * @returns {boolean}
     */
    isUnremovable(node) {
        return this.getResource("unremovable_node_predicates").some((p) => p(node));
    }

    /**
     * Remove every removable format from the selection.
     *
     * A non-collapsed selection is stripped in the DOM immediately. A collapsed
     * one records a pending removal per active format instead, applied to the
     * next character typed (see {@link applyPendingFormats}).
     */
    removeAllFormats() {
        const selection = this.dependencies.selection.getEditableSelection();
        const targetedNodes = this.dependencies.selection.getTargetedNodes();
        if (selection.isCollapsed) {
            this.activeFormats = {}; // discard pending "apply" intents
            for (const format of Object.keys(formatsSpecs)) {
                if (
                    formatsSpecs[format].removeStyle &&
                    this.hasSelectionFormat(format, targetedNodes)
                ) {
                    this.activeFormats[format] = { applyStyle: false };
                }
            }
            this.dispatchTo("format_requested_handlers");
            // Colour is not in `formatsSpecs`: the colour plugin removes it
            // through this resource. Keep that eager, so a collapsed Remove
            // Format still clears the colour as it always has.
            this.dispatchTo("remove_all_formats_handlers");
            this.dependencies.history.addStep();
            return;
        }
        this.removeFormats(Object.keys(formatsSpecs), targetedNodes);
        this.dispatchTo("remove_all_formats_handlers");
        this.dependencies.history.addStep();
    }

    removeFontSizeFormat(el) {
        for (const node of [el, ...descendants(el)]) {
            removeFormat(node, formatsSpecs.fontSize);
            removeFormat(node, formatsSpecs.setFontSizeClassName);
        }
    }

    /**
     * @param {String} format
     * @param {Node[]} [targetedNodes]
     * @returns {boolean}
     */
    hasSelectionFormat(
        format,
        targetedNodes = this.dependencies.selection.getTargetedNodes(),
    ) {
        const targetedTextNodes = targetedNodes.filter(
            (node) =>
                node.matches?.(PROTECTED_QWEB_SELECTOR) ||
                (isTextNode(node) && (isVisibleTextNode(node) || isZWS(node))),
        );
        const isFormatted = formatsSpecs[format].isFormatted;
        return targetedTextNodes.some((n) =>
            isFormatted(n, { editable: this.editable }),
        );
    }
    /**
     * @param {String} format
     * @param {Node[]} [targetedNodes]
     * @returns {boolean}
     */
    isSelectionFormat(
        format,
        targetedNodes = this.dependencies.selection.getTargetedNodes(),
    ) {
        const isFormatted = formatsSpecs[format].isFormatted;
        const isNonFormattedWhiteSpaces = (node) =>
            /^(\s|\n)+$/.test(node.nodeValue) &&
            !isFormatted(node, { editable: this.editable });
        const targetedTextNodes = targetedNodes.filter(
            (node) =>
                isTextNode(node) &&
                !isNonFormattedWhiteSpaces(node) &&
                this.dependencies.selection.isNodeEditable(node) &&
                (this.checkPredicates("is_formattable_node_predicates", node) ?? true),
        );
        return (
            targetedTextNodes.length &&
            targetedTextNodes.every(
                (node) =>
                    isZwnbsp(node) ||
                    isEmptyTextNode(node) ||
                    isFormatted(node, { editable: this.editable }),
            )
        );
    }

    hasAnyFormat(targetedNodes) {
        for (const format of Object.keys(formatsSpecs)) {
            if (
                formatsSpecs[format].removeStyle &&
                this.hasSelectionFormat(format, targetedNodes)
            ) {
                if (format === "bold") {
                    const textNodes = targetedNodes.filter(isTextNode);
                    if (!textNodes.some((n) => hasExplicitBoldFormatting(n))) {
                        continue;
                    }
                }
                return true;
            }
        }
        return targetedNodes.some((node) =>
            this.getResource("has_format_predicates").some((predicate) =>
                predicate(node),
            ),
        );
    }

    /**
     * Toggle or set a format on the current selection.
     *
     * A non-collapsed selection is formatted in the DOM straight away. A
     * collapsed one mutates nothing: the intent is recorded in
     * {@link activeFormats} and applied the next time the user types or an
     * insert happens (see {@link applyPendingFormats}).
     *
     * @param {string} formatName
     * @param {Object} [options]
     * @param {boolean} [options.applyStyle]
     * @param {Object} [options.formatProps]
     */
    requestFormat(formatName, options) {
        const selection = this.dependencies.selection.getEditableSelection();
        if (!selection.isCollapsed) {
            this.formatSelection(formatName, options);
            return;
        }
        const domActive = this.isSelectionFormat(formatName);
        const pending = this.activeFormats[formatName];
        if (options?.applyStyle === undefined && pending?.applyStyle === !domActive) {
            // Toggling back to what the DOM already says: drop the intent.
            delete this.activeFormats[formatName];
        } else {
            this.activeFormats[formatName] = {
                applyStyle: options?.applyStyle ?? !(pending?.applyStyle ?? domActive),
                formatProps: options?.formatProps,
            };
        }
        this.dispatchTo("format_requested_handlers");
    }

    formatSelection(formatName, options) {
        this.dispatchTo("format_selection_handlers", formatName, options);
        if (this._formatSelection(formatName, options) && !options?.removeFormat) {
            this.dependencies.history.addStep();
        }
    }

    _formatSelection(
        formatName,
        { applyStyle, formatProps, removeFormat: isRemoveFormat } = {},
    ) {
        const deepSelection =
            this.dependencies.selection.getSelectionData().deepEditableSelection;
        const anchorElement = deepSelection.anchorNode;
        const focusElement = deepSelection.focusNode;
        if (
            anchorElement === focusElement &&
            !isContentEditable(anchorElement) &&
            !closestElement(anchorElement, PROTECTED_QWEB_SELECTOR)
        ) {
            return;
        }
        this.dependencies.selection.selectAroundNonEditable();
        this.dependencies.split.splitSelection();
        if (typeof applyStyle === "undefined") {
            applyStyle = !this.isSelectionFormat(formatName);
        }

        const cursor = this.dependencies.selection.preserveSelection();
        const systemNodesSelector = this.getResource("system_node_selectors").join(
            ", ",
        );
        const selectedTextNodes = /** @type { Text[] } */ (
            this.dependencies.selection
                .getTargetedNodes()
                .filter(
                    (n) =>
                        (!systemNodesSelector ||
                            !closestElement(n, systemNodesSelector)) &&
                        ((isTextNode(n) && (isVisibleTextNode(n) || isZWS(n))) ||
                            (n.nodeName === "BR" &&
                                (isFakeLineBreak(n) ||
                                    previousLeaf(n, closestBlock(n))?.nodeName ===
                                        "BR"))) &&
                        isContentEditable(n),
                )
        );
        const unformattedTextNodes = selectedTextNodes.filter((n) => {
            if (!(this.checkPredicates("is_formattable_node_predicates", n) ?? true)) {
                return false;
            }
            const listItem = closestElement(n, "li");
            if (
                listItem &&
                this.dependencies.selection.areNodeContentsFullySelected(listItem)
            ) {
                const hasFontSizeStyle =
                    formatName === "setFontSizeClassName"
                        ? listItem.classList.contains(formatProps?.className)
                        : listItem.style.fontSize;
                return !hasFontSizeStyle;
            }
            return true;
        });

        const tagetedFieldNodes = new Set(
            this.dependencies.selection
                .getTargetedNodes()
                .map((n) => closestElement(n, "*[t-field],*[t-out],*[t-esc]"))
                .filter(Boolean),
        );
        const formatSpec = formatsSpecs[formatName];
        for (const node of unformattedTextNodes) {
            const inlineAncestors = [];
            /** @type { Node } */
            let currentNode = node;
            let parentNode = node.parentElement;

            const isClassListSplittable = (classList) =>
                [...classList].every((className) =>
                    this.getResource("format_class_predicates").some((cb) =>
                        cb(className),
                    ),
                );

            if (
                parentNode &&
                !isBlock(parentNode) &&
                this.dependencies.split.isUnsplittable(parentNode) &&
                this.dependencies.selection.areNodeContentsFullySelected(parentNode) &&
                !isContentEditableAncestor(parentNode)
            ) {
                inlineAncestors.push(parentNode);
            }

            while (
                parentNode &&
                !isBlock(parentNode) &&
                !this.dependencies.split.isUnsplittable(parentNode) &&
                (parentNode.classList.length === 0 ||
                    isClassListSplittable(parentNode.classList))
            ) {
                const newLastAncestorInlineFormat =
                    this.dependencies.split.splitAroundUntil(currentNode, parentNode);
                removeFormat(newLastAncestorInlineFormat, formatSpec, cursor);
                if (
                    ["setFontSizeClassName", "fontSize"].includes(formatName) &&
                    applyStyle
                ) {
                    removeClass(newLastAncestorInlineFormat, "o_default_font_size");
                }
                if (newLastAncestorInlineFormat.isConnected) {
                    inlineAncestors.push(newLastAncestorInlineFormat);
                    currentNode = newLastAncestorInlineFormat;
                }

                parentNode = currentNode.parentElement;
            }

            const firstBlockOrClassHasFormat = formatSpec.isFormatted(
                parentNode,
                formatProps,
            );
            if (firstBlockOrClassHasFormat && !applyStyle) {
                const isParentNodeBlockAndCompletelySelected =
                    isBlock(parentNode) &&
                    this.dependencies.selection.areNodeContentsFullySelected(
                        parentNode,
                    );
                if (
                    isParentNodeBlockAndCompletelySelected &&
                    formatName === "setFontSizeClassName"
                ) {
                    for (const node of [
                        parentNode,
                        ...descendants(parentNode).filter(isElement),
                    ]) {
                        removeFormat(node, formatSpec, cursor);
                    }
                } else {
                    const skipNeutral =
                        isRemoveFormat &&
                        formatName === "bold" &&
                        !parentNode.style?.fontWeight;
                    if (!skipNeutral) {
                        formatSpec.addNeutralStyle &&
                            formatSpec.addNeutralStyle(
                                getOrCreateSpan(node, inlineAncestors, cursor),
                            );
                    }
                }
            } else if (
                (!firstBlockOrClassHasFormat || parentNode.nodeName === "LI") &&
                applyStyle
            ) {
                const tag =
                    formatSpec.tagName &&
                    this.document.createElement(formatSpec.tagName);
                if (tag) {
                    cursor.update(callbacksForCursorUpdate.after(node, tag));
                    node.after(tag);
                    cursor.update(callbacksForCursorUpdate.append(tag, node));
                    tag.append(node);

                    if (!formatSpec.isFormatted(tag, formatProps)) {
                        cursor.remapNode(tag, node);
                        tag.after(node);
                        tag.remove();
                        formatSpec.addStyle(
                            getOrCreateSpan(node, inlineAncestors, cursor),
                            formatProps,
                        );
                    }
                } else if (
                    formatName !== "fontSize" ||
                    formatProps.size !== undefined
                ) {
                    formatSpec.addStyle(
                        getOrCreateSpan(node, inlineAncestors, cursor),
                        formatProps,
                    );
                }
            }
        }

        for (const targetedFieldNode of tagetedFieldNodes) {
            if (applyStyle) {
                formatSpec.addStyle(targetedFieldNode, formatProps);
            } else {
                formatSpec.removeStyle(targetedFieldNode);
            }
        }

        cursor.restore();

        if (
            unformattedTextNodes.length === 1 &&
            unformattedTextNodes[0] &&
            unformattedTextNodes[0].textContent === "\u200B"
        ) {
            const [anchorNode, anchorOffset, focusNode, focusOffset] = [
                ...leftPos(unformattedTextNodes[0]),
                ...rightPos(unformattedTextNodes[0]),
            ];
            this.dependencies.selection.setSelection({
                anchorNode,
                anchorOffset,
                focusNode,
                focusOffset,
            });
            return !!tagetedFieldNodes.size;
        }
        return true;
    }

    normalize(root) {
        for (const el of selectElements(root, "[data-oe-zws-empty-inline]")) {
            if (!allWhitespaceRegex.test(el.textContent)) {
                delete el.dataset.oeZwsEmptyInline;
                this.cleanZWS(el);
                if (
                    el.tagName === "SPAN" &&
                    el.getAttributeNames().length === 0 &&
                    el.classList.length === 0
                ) {
                    unwrapContents(el);
                }
            }
        }
        this.mergeAdjacentInlines(root);
    }

    cleanForSave({ root, preserveSelection = false } = {}) {
        for (const element of root.querySelectorAll("[data-oe-zws-empty-inline]")) {
            let currentElement = element.parentElement;
            this.cleanElement(element, { preserveSelection });
            while (
                currentElement &&
                !isBlock(currentElement) &&
                !currentElement.childNodes.length
            ) {
                const parentElement = currentElement.parentElement;
                currentElement.remove();
                currentElement = parentElement;
            }
            if (currentElement && isBlock(currentElement)) {
                fillEmpty(currentElement);
            }
        }
        this.mergeAdjacentInlines(root, { preserveSelection });
    }

    cleanElement(element, { preserveSelection }) {
        if (!allWhitespaceRegex.test(element.textContent)) {
            delete element.dataset.oeZwsEmptyInline;
            this.cleanZWS(element, { preserveSelection });
            return;
        }
        if (this.getResource("unremovable_node_predicates").some((p) => p(element))) {
            return;
        }
        if (
            ![...element.classList].every((c) =>
                this.getResource("format_class_predicates").some((p) => p(c)),
            )
        ) {
            return;
        }
        const restore = prepareUpdate(...leftPos(element), ...rightPos(element));
        element.remove();
        restore();
    }

    cleanZWS(element, { preserveSelection = true } = {}) {
        const textNodes = descendants(element).filter(isTextNode);
        const cursors = preserveSelection
            ? this.dependencies.selection.preserveSelection()
            : null;
        for (const node of textNodes) {
            cleanTextNode(node, "\u200B", cursors);
        }
        cursors?.restore();
    }

    insertText(selection, content) {
        if (selection.anchorNode.nodeType === Node.TEXT_NODE) {
            selection = this.dependencies.selection.setSelection(
                {
                    anchorNode: selection.anchorNode.parentElement,
                    anchorOffset: splitTextNode(
                        selection.anchorNode,
                        selection.anchorOffset,
                    ),
                },
                { normalize: false },
            );
        }

        const txt = this.document.createTextNode(content || "#");
        const restore = prepareUpdate(selection.anchorNode, selection.anchorOffset);
        selection.anchorNode.insertBefore(
            txt,
            selection.anchorNode.childNodes[selection.anchorOffset],
        );
        restore();
        const [anchorNode, anchorOffset, focusNode, focusOffset] = boundariesOut(txt);
        this.dependencies.selection.setSelection(
            { anchorNode, anchorOffset, focusNode, focusOffset },
            { normalize: false },
        );
        return txt;
    }

    /**
     * @returns {Node}
     */
    getOrCreateZws() {
        const selection = this.dependencies.selection.getEditableSelection();
        if (
            selection.anchorNode.nodeType === Node.TEXT_NODE &&
            selection.anchorNode.textContent === "\u200b"
        ) {
            return selection.anchorNode;
        }
        const zws = this.insertText(selection, "\u200B");
        splitTextNode(zws, selection.anchorOffset);
        return zws;
    }

    /**
     * Discard the pending format intents when the selection moves.
     */
    clearPendingFormats() {
        if (this.skipNextFormatClear) {
            this.skipNextFormatClear = false;
            return;
        }
        this.activeFormats = {};
    }

    /**
     * Write the intents recorded in {@link activeFormats} onto a ZWS at the
     * caret, which is the first moment the DOM has to change.
     */
    applyPendingFormats() {
        if (!Object.keys(this.activeFormats).length) {
            return;
        }
        this.getOrCreateZws();
        for (const [formatName, { applyStyle, formatProps }] of Object.entries(
            this.activeFormats,
        )) {
            this.formatSelection(formatName, { applyStyle, formatProps });
        }
        this.activeFormats = {};
    }

    beforeInsert() {
        if (this.dependencies.selection.getEditableSelection().isCollapsed) {
            this.applyPendingFormats();
        }
    }

    onBeforeInput(ev) {
        if (
            ev.inputType.startsWith("format") &&
            !isHtmlContentSupported(this.dependencies.selection.getEditableSelection())
        ) {
            ev.preventDefault();
        }
        if (ev.inputType === "insertText") {
            const selection = this.dependencies.selection.getEditableSelection();
            if (!selection.isCollapsed) {
                return;
            }
            this.applyPendingFormats();
        }
    }

    /**
     * @param {Node} root
     * @param {Object} [options]
     * @param {boolean} [options.preserveSelection=true]
     */
    mergeAdjacentInlines(root, { preserveSelection = true } = {}) {
        let selectionToRestore = null;
        for (const node of [root, ...descendants(root)].filter(isElement)) {
            if (this.shouldBeMergedWithPreviousSibling(node)) {
                if (preserveSelection) {
                    selectionToRestore ??=
                        this.dependencies.selection.preserveSelection();
                    selectionToRestore.update(callbacksForCursorUpdate.merge(node));
                }
                if (node.matches("code.o_inline_code")) {
                    while (
                        node.previousSibling?.nodeType === Node.TEXT_NODE &&
                        /^\uFEFF*$/.test(node.previousSibling.nodeValue)
                    ) {
                        node.previousSibling.remove();
                    }
                }
                node.previousSibling.append(...childNodes(node));
                node.remove();
            }
        }
        selectionToRestore?.restore();
    }

    shouldBeMergedWithPreviousSibling(node) {
        const isMergeable = (node) =>
            FORMATTABLE_TAGS.includes(node.nodeName) &&
            !this.getResource("unsplittable_node_predicates").some((predicate) =>
                predicate(node),
            );
        let previousSibling = node.previousSibling;
        if (node.matches("code.o_inline_code")) {
            while (
                previousSibling?.nodeType === Node.TEXT_NODE &&
                /^\uFEFF*$/.test(previousSibling.nodeValue)
            ) {
                previousSibling = previousSibling.previousSibling;
            }
        }
        return (
            !isSelfClosingElement(node) &&
            areSimilarElements(node, previousSibling) &&
            isMergeable(node)
        );
    }
}

function getOrCreateSpan(node, ancestors, cursor) {
    const document = node.ownerDocument;
    const span = ancestors.find(
        (element) => element.tagName === "SPAN" && element.isConnected,
    );
    const lastInlineAncestor = ancestors.findLast(
        (element) => !isBlock(element) && element.isConnected,
    );
    if (span) {
        return span;
    } else {
        const span = document.createElement("span");
        if (lastInlineAncestor) {
            cursor?.update(callbacksForCursorUpdate.after(lastInlineAncestor, span));
            lastInlineAncestor.after(span);
            cursor?.update(callbacksForCursorUpdate.append(span, lastInlineAncestor));
            span.append(lastInlineAncestor);
        } else {
            cursor?.update(callbacksForCursorUpdate.after(node, span));
            node.after(span);
            cursor?.update(callbacksForCursorUpdate.append(span, node));
            span.append(node);
        }
        return span;
    }
}
function hasExplicitBoldFormatting(textNode) {
    const block = closestBlock(textNode);
    let el = closestElement(textNode);
    while (el && el !== block) {
        if (["STRONG", "B"].includes(el.tagName) || el.style?.fontWeight) {
            return true;
        }
        el = el.parentElement;
    }
    return Boolean(block?.style?.fontWeight);
}

function removeFormat(node, formatSpec, cursor) {
    const document = node.ownerDocument;
    node = closestElement(node);
    if (!node) {
        return;
    }
    if (formatSpec.hasStyle(node)) {
        formatSpec.removeStyle(node);
        if (
            ["SPAN", "FONT"].includes(node.tagName) &&
            !node.getAttributeNames().length
        ) {
            cursor?.update(callbacksForCursorUpdate.unwrap(node));
            return unwrapContents(node);
        }
    }

    if (formatSpec.isTag && formatSpec.isTag(node)) {
        const attributesNames = node
            .getAttributeNames()
            .filter((name) => name !== "data-oe-zws-empty-inline");
        if (attributesNames.length) {
            const newNode = document.createElement("span");
            while (node.firstChild) {
                cursor?.update(
                    callbacksForCursorUpdate.append(newNode, node.firstChild),
                );
                newNode.appendChild(node.firstChild);
            }
            for (let index = node.attributes.length - 1; index >= 0; --index) {
                newNode.attributes.setNamedItem(node.attributes[index].cloneNode());
            }
            cursor?.remapNode(node, newNode);
            node.parentNode.replaceChild(newNode, node);
        } else if (
            node.getAttributeNames().length === 1 &&
            node.hasAttribute("data-oe-zws-empty-inline")
        ) {
            cursor?.update(callbacksForCursorUpdate.remove(node));
            node.remove();
        } else {
            cursor?.update(callbacksForCursorUpdate.unwrap(node));
            unwrapContents(node);
        }
    }
}
