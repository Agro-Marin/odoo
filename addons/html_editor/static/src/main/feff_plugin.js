/** @odoo-module native */
import { Plugin } from "@html_editor/plugin";
import { cleanEmptyAncestors, cleanTextNode } from "@html_editor/utils/dom";
import { isTextNode, isZwnbsp } from "@html_editor/utils/dom_info";
import { prepareUpdate } from "@html_editor/utils/dom_state";
import { descendants, selectElements } from "@html_editor/utils/dom_traversal";
import { leftPos, rightPos } from "@html_editor/utils/position";
import { callbacksForCursorUpdate } from "@html_editor/utils/selection";

import { withSequence } from "../utils/resource.js";

/** @typedef {import("../core/selection_plugin").Cursors} Cursors */

/**
 * @typedef { Object } FeffShared
 * @property { FeffPlugin['addFeff'] } addFeff
 * @property { FeffPlugin['removeFeffs'] } removeFeffs
 * @property { FeffPlugin['surroundWithFeffs'] } surroundWithFeffs
 */

/**
 * @typedef {((node: Node) => boolean)[]} legit_feff_predicates
 * @typedef {((root: EditorContext["editable"], cursors: Cursors) => Node[])[]} feff_providers
 * @typedef {(() => string)[]} selectors_for_feff_providers
 */

export class FeffPlugin extends Plugin {
    static id = "feff";
    static dependencies = ["selection"];
    static shared = ["addFeff", "removeFeffs", "surroundWithFeffs"];

    /** @type {import("plugins").EditorResources} */
    resources = {
        normalize_handlers: withSequence(Infinity, this.updateFeffs.bind(this)),
        clean_for_save_handlers: this.cleanForSave.bind(this),
        intangible_char_for_keyboard_navigation_predicates: (ev, char, lastSkipped) =>
            char === "\uFEFF" && (ev.shiftKey || lastSkipped !== "\uFEFF"),
        clipboard_content_processors: this.processContentForClipboard.bind(this),
        clipboard_text_processors: (text) => text.replace(/\ufeff/g, ""),
    };

    cleanForSave({ root, preserveSelection = false }) {
        if (preserveSelection) {
            const cursors = this.getCursors();
            this.removeFeffs(root, cursors);
            cursors.restore();
        } else {
            this.removeFeffs(root, null);
        }
    }

    /**
     * @param {Element} root
     * @param {Cursors} [cursors]
     * @param {Object} [options]
     */
    removeFeffs(root, cursors, { exclude = () => false } = {}) {
        const hasFeff = (node) =>
            isTextNode(node) && node.textContent.includes("\ufeff");
        const isEditable = (node) => node.parentElement.isContentEditable;
        const composedFilter = (node) =>
            hasFeff(node) && isEditable(node) && !exclude(node);

        for (const node of descendants(root).filter(composedFilter)) {
            const restoreSpaces = prepareUpdate(...leftPos(node), ...rightPos(node));
            const parent = node.parentNode;
            cleanTextNode(node, "\ufeff", cursors);
            cleanEmptyAncestors(
                parent,
                cursors,
                (node) =>
                    node.hasAttribute("data-oe-zws-empty-inline") ||
                    this.getResource("unremovable_node_predicates").some((predicate) =>
                        predicate(node),
                    ),
            );
            restoreSpaces();
        }
    }

    /**
     * @param {Element} element
     * @param {'before'|'after'|'prepend'|'append'} position
     * @param {Cursors} [cursors]
     * @returns {Node}
     */
    addFeff(element, position, cursors) {
        const feff = this.document.createTextNode("\ufeff");
        cursors?.update(callbacksForCursorUpdate[position](element, feff));
        element[position](feff);
        return feff;
    }

    surroundWithFeffs(node, cursors) {
        const addFeff = (position) => {
            const c = position === "append" ? null : cursors;
            return this.addFeff(node, position, c);
        };

        const zwnbspNodes = [];
        for (const [position, relation] of [
            ["before", "previousSibling"],
            ["after", "nextSibling"],
            ["prepend", "firstChild"],
            ["append", "lastChild"],
        ]) {
            const candidate = node[relation];
            const feff =
                isZwnbsp(candidate) && !zwnbspNodes.includes(candidate)
                    ? candidate
                    : addFeff(position);
            zwnbspNodes.push(feff);
        }
        return zwnbspNodes;
    }

    /**
     * @param {Element} root
     * @param {Cursors} cursors
     * @returns {Node[]}
     */
    padWithFeffs(root, cursors) {
        const combinedSelector = this.getResource("selectors_for_feff_providers")
            .map((provider) => provider())
            .join(", ");
        if (!combinedSelector) {
            return [];
        }
        const elements = [...selectElements(root, combinedSelector)];
        const isEditable = (node) => node.parentElement?.isContentEditable;
        const feffNodes = elements
            .filter(isEditable)
            .flatMap((el) => {
                const addFeff = (position) => this.addFeff(el, position, cursors);
                return [
                    isZwnbsp(el.previousSibling)
                        ? el.previousSibling
                        : addFeff("before"),
                    isZwnbsp(el.nextSibling) ? el.nextSibling : addFeff("after"),
                ];
            })
            .filter(
                (feff, i, array) => !(i > 0 && areCloseSiblings(array[i - 1], feff)),
            );
        return feffNodes;
    }

    updateFeffs(root) {
        const cursors = this.getCursors();
        const feffNodesBasedOnSelectors = this.padWithFeffs(root, cursors);
        const customFeffNodes = this.getResource("feff_providers").flatMap((p) =>
            p(root, cursors),
        );
        const feffNodesToKeep = new Set([
            ...feffNodesBasedOnSelectors,
            ...customFeffNodes,
        ]);
        this.removeFeffs(root, cursors, {
            exclude: (node) =>
                feffNodesToKeep.has(node) ||
                this.getResource("legit_feff_predicates").some((predicate) =>
                    predicate(node),
                ),
        });
        cursors.restore();
    }

    getCursors() {
        const cursors = this.dependencies.selection.preserveSelection();
        const originalUpdate = cursors.update.bind(cursors);
        const originalRestore = cursors.restore.bind(cursors);
        let shouldRestore = false;
        cursors.update = (...args) => {
            shouldRestore = true;
            return originalUpdate(...args);
        };
        cursors.restore = () => {
            if (shouldRestore) {
                originalRestore();
            }
        };
        return cursors;
    }

    processContentForClipboard(clonedContent) {
        descendants(clonedContent)
            .filter(isTextNode)
            .filter((node) => node.textContent.includes("\ufeff"))
            .forEach(
                (node) => (node.textContent = node.textContent.replace(/\ufeff/g, "")),
            );
        return clonedContent;
    }
}

/**
 * @param {Node} a
 * @param {Node} b
 */
function areCloseSiblings(a, b) {
    let next = a.nextSibling;
    while (next && isTextNode(next) && !next.textContent) {
        next = next.nextSibling;
    }
    return next === b;
}
