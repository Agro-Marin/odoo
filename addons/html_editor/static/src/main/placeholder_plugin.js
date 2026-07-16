/** @odoo-module native */
import { baseContainerGlobalSelector } from "@html_editor/utils/base_container";
import { isEmptyBlock } from "@html_editor/utils/dom_info";
import { childNodes } from "@html_editor/utils/dom_traversal";
import { withSequence } from "@html_editor/utils/resource";

import { Plugin } from "../plugin.js";

export class PlaceholderPlugin extends Plugin {
    static id = "placeholder";
    /** @type {import("plugins").EditorResources} */
    resources = {
        ...(this.config.placeholder && {
            hints: [
                withSequence(1, {
                    selector: `.odoo-editor-editable:not(:focus) > ${baseContainerGlobalSelector}:only-child`,
                    text: this.config.placeholder,
                }),
            ],
            hint_targets_providers: (selectionData, editable) => {
                const el = editable.firstChild;
                if (
                    !selectionData.documentSelectionIsInEditable &&
                    childNodes(editable).length === 1 &&
                    isEmptyBlock(el) &&
                    el.matches(baseContainerGlobalSelector)
                ) {
                    return [el];
                } else {
                    return [];
                }
            },
        }),
    };
}
