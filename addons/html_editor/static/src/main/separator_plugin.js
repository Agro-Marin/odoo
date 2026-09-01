/** @odoo-module native */
import { isHtmlContentSupported } from "@html_editor/core/selection_plugin";
import { removeClass } from "@html_editor/utils/dom";
import { withSequence } from "@html_editor/utils/resource";
import { _t } from "@web/core/translation";

import { Plugin } from "../plugin.js";
import { closestBlock } from "../utils/blocks.js";
import { fillEmpty } from "../utils/dom.js";
import { isEmptyBlock, paragraphRelatedElementsSelector } from "../utils/dom_info.js";
import { closestElement, firstLeaf, selectElements } from "../utils/dom_traversal.js";

export class SeparatorPlugin extends Plugin {
    static id = "separator";
    static dependencies = [
        "selection",
        "history",
        "split",
        "delete",
        "lineBreak",
        "baseContainer",
    ];
    /** @type {import("plugins").EditorResources} */
    resources = {
        user_commands: [
            {
                id: "insertSeparator",
                title: _t("Separator"),
                description: _t("Insert a horizontal rule separator"),
                icon: "fa-minus",
                run: this.insertSeparator.bind(this),
                isAvailable: isHtmlContentSupported,
            },
        ],
        powerbox_items: withSequence(1, {
            categoryId: "structure",
            commandId: "insertSeparator",
            keywords: [_t("divider"), _t("line")],
        }),
        content_not_editable_providers: (rootEl) => [...selectElements(rootEl, "hr")],
        contenteditable_to_remove_selector: "hr[contenteditable]",
        shorthands: [
            {
                pattern: /^---$/,
                commandId: "insertSeparator",
            },
        ],

        selectionchange_handlers: this.handleSelectionInHr.bind(this),
        deselect_custom_selected_nodes_handlers: this.deselectHR.bind(this),
        clean_for_save_handlers: ({ root }) => {
            this.deselectHR(root);
        },
    };

    insertSeparator() {
        let selection =
            this.dependencies.selection.getSelectionData().deepEditableSelection;
        const block = closestBlock(selection.startContainer);
        // A list item is not a paragraph-related element, so inside one the
        // lookup below finds nothing and the command used to do nothing at
        // all. The list plugin answers this by splitting the list and
        // outdenting the caret out of it, which moves the selection.
        this.dispatchTo("before_insert_separator_handlers", block);
        selection =
            this.dependencies.selection.getSelectionData().deepEditableSelection;
        const element = closestElement(
            selection.startContainer,
            paragraphRelatedElementsSelector,
        );

        if (element && element !== this.editable) {
            const sep = this.document.createElement("hr");
            const firstLeafNode = firstLeaf(block);
            if (
                isEmptyBlock(element) ||
                (selection.anchorNode === firstLeafNode && selection.anchorOffset === 0)
            ) {
                element.before(sep);
            } else {
                element.after(sep);
                const baseContainer =
                    this.dependencies.baseContainer.createBaseContainer();
                fillEmpty(baseContainer);
                sep.after(baseContainer);
                this.dependencies.selection.setCursorStart(baseContainer);
            }
        }
        this.dependencies.history.addStep();
    }

    deselectHR(root = this.editable) {
        for (const hr of root.querySelectorAll(".o_selected_hr")) {
            removeClass(hr, "o_selected_hr");
        }
    }

    handleSelectionInHr(selectionData) {
        this.deselectHR();
        if (!selectionData.documentSelectionIsInEditable) {
            return;
        }
        const targetedNodes = this.dependencies.selection.getTargetedNodes();
        for (const node of targetedNodes) {
            if (node.nodeName === "HR") {
                node.classList.toggle("o_selected_hr", true);
            }
        }
    }
}
