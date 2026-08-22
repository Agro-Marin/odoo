/** @odoo-module native */
import { withSequence } from "@html_editor/utils/resource";

import { Plugin } from "../plugin.js";
import { isProtecting, isUnprotecting } from "../utils/dom_info.js";
import { childNodes } from "../utils/dom_traversal.js";

const PROTECTED_SELECTOR = `[data-oe-protected="true"],[data-oe-protected=""]`;
const UNPROTECTED_SELECTOR = `[data-oe-protected="false"]`;

/**
 * @typedef { Object } ProtectedNodeShared
 * @property { ProtectedNodePlugin['setProtectingNode'] } setProtectingNode
 * @typedef { import("./history_plugin").HistoryMutationRecord } HistoryMutationRecord
 */

export class ProtectedNodePlugin extends Plugin {
    static id = "protectedNode";
    static shared = ["setProtectingNode"];
    /** @type {import("plugins").EditorResources} */
    resources = {
        clean_for_save_handlers: ({ root }) => this.cleanForSave(root),
        normalize_handlers: withSequence(0, this.normalize.bind(this)),
        before_filter_mutation_record_handlers:
            this.beforeFilteringMutationRecords.bind(this),

        unsplittable_node_predicates: [
            isProtecting,
            isUnprotecting,
        ],
        savable_mutation_record_predicates: this.isMutationRecordSavable.bind(this),
        removable_descendants_providers: this.filterDescendantsToRemove.bind(this),
    };

    setup() {
        this.protectedNodes = new WeakSet();
    }

    filterDescendantsToRemove(elem) {
        if (isProtecting(elem)) {
            const descendantsToRemove = [];
            for (const candidate of elem.querySelectorAll(UNPROTECTED_SELECTOR)) {
                if (candidate.closest(PROTECTED_SELECTOR) === elem) {
                    descendantsToRemove.push(...childNodes(candidate));
                }
            }
            return descendantsToRemove;
        }
    }

    protectNode(node) {
        if (node.nodeType === Node.ELEMENT_NODE) {
            if (node.matches(UNPROTECTED_SELECTOR)) {
                this.unProtectDescendants(node);
            } else if (!this.protectedNodes.has(node)) {
                this.protectDescendants(node);
            }
        }
        this.protectedNodes.add(node);
    }

    unProtectNode(node) {
        if (node.nodeType === Node.ELEMENT_NODE) {
            if (node.matches(PROTECTED_SELECTOR)) {
                this.protectDescendants(node);
            } else if (this.protectedNodes.has(node)) {
                this.unProtectDescendants(node);
            }
        }
        this.protectedNodes.delete(node);
    }

    protectDescendants(node) {
        let child = node.firstChild;
        while (child) {
            this.protectNode(child);
            child = child.nextSibling;
        }
    }

    unProtectDescendants(node) {
        let child = node.firstChild;
        while (child) {
            this.unProtectNode(child);
            child = child.nextSibling;
        }
    }

    /**
     * @param {HistoryMutationRecord[]} records
     */
    beforeFilteringMutationRecords(records) {
        for (const record of records) {
            if (record.type === "childList") {
                if (record.target.nodeType !== Node.ELEMENT_NODE) {
                    return;
                }
                const addedNodes = record.addedTrees.map((tree) => tree.node);
                if (
                    (this.protectedNodes.has(record.target) &&
                        !record.target.matches(UNPROTECTED_SELECTOR)) ||
                    record.target.matches(PROTECTED_SELECTOR)
                ) {
                    for (const addedNode of addedNodes) {
                        this.protectNode(addedNode);
                    }
                } else if (
                    !this.protectedNodes.has(record.target) ||
                    record.target.matches(UNPROTECTED_SELECTOR)
                ) {
                    for (const addedNode of addedNodes) {
                        this.unProtectNode(addedNode);
                    }
                }
            }
        }
    }

    /**
     * @param {HistoryMutationRecord} record
     * @return {boolean}
     */
    isMutationRecordSavable(record) {
        if (record.type === "childList") {
            return !(
                (this.protectedNodes.has(record.target) &&
                    !record.target.matches(UNPROTECTED_SELECTOR)) ||
                record.target.matches(PROTECTED_SELECTOR)
            );
        }
        return !this.protectedNodes.has(record.target);
    }

    forEachProtectingElem(elem, callback) {
        const selector = `[data-oe-protected]`;
        const protectingNodes = [...elem.querySelectorAll(selector)].reverse();
        if (elem.matches(selector)) {
            protectingNodes.push(elem);
        }
        for (const protectingNode of protectingNodes) {
            if (protectingNode.dataset.oeProtected === "false") {
                callback(protectingNode, false);
            } else {
                callback(protectingNode, true);
            }
        }
    }

    normalize(elem) {
        this.forEachProtectingElem(elem, this.setProtectingNode.bind(this));
    }

    setProtectingNode(elem, protecting) {
        elem.dataset.oeProtected = protecting;
        if (protecting) {
            elem.setAttribute("contenteditable", "false");
            this.protectDescendants(elem);
        } else {
            elem.setAttribute("contenteditable", "true");
            this.unProtectDescendants(elem);
        }
    }

    cleanForSave(clone) {
        this.forEachProtectingElem(clone, (protectingNode) => {
            protectingNode.removeAttribute("contenteditable");
        });
    }
}
