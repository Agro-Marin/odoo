/** @odoo-module native */
import { Plugin } from "@html_editor/plugin";
import { removeClass } from "@html_editor/utils/dom";
import { isEditorTab, isEmptyBlock, isProtected } from "@html_editor/utils/dom_info";
import {
    closestElement,
    descendants,
    firstLeaf,
    selectElements,
} from "@html_editor/utils/dom_traversal";
import { debounce } from "@web/core/utils/timing";

import { closestBlock } from "../utils/blocks.js";

/**
 * @typedef {import("@html_editor/editor").EditorContext} EditorContext
 * @typedef {import("@html_editor/core/selection_plugin").SelectionData} SelectionData
 * @typedef {import("plugins").CSSSelector} CSSSelector
 * @typedef {import("plugins").TranslatedString} TranslatedString
 */

/**
 * @typedef {((
 * selectionData: SelectionData,
 * editable: EditorContext["editable"]
 * ) => HTMLElement[] | NodeList)[]} hint_targets_providers
 * @typedef {{ selector: CSSSelector; text: TranslatedString; }[]} hints
 */

export class HintPlugin extends Plugin {
    static id = "hint";
    static dependencies = ["history", "selection"];
    /** @type {import("plugins").EditorResources} */
    resources = {
        selectionchange_handlers: this.triggerDebouncedUpdateHints.bind(this),
        external_history_step_handlers: () => {
            this.clearHints();
            this.updateHints();
        },
        normalize_handlers: this.normalize.bind(this),
        clean_for_save_handlers: ({ root }) => this.clearHints(root),
        content_updated_handlers: this.updateHints.bind(this),

        /** Predicates */
        // The power buttons sit on the hint line. When the hint is
        // suppressed they would overlap the text, so hide them too.
        power_buttons_visibility_predicates: ({ anchorNode }) =>
            Boolean(closestElement(anchorNode, ".o-we-hint")),

        hint_targets_providers: (selectionData, editable) => {
            if (
                !selectionData.currentSelectionIsInEditable ||
                !selectionData.documentSelection
            ) {
                return [];
            }
            const blockEl = closestBlock(selectionData.documentSelection.anchorNode);
            if (this.dependencies.selection.isNodeEditable(blockEl)) {
                return [blockEl];
            } else {
                return [];
            }
        },
        system_classes: ["o-we-hint"],
        system_attributes: ["o-we-hint-text"],
    };

    setup() {
        this.updateHints(this.editable);
        const shouldDebounce = this.config.debounceHints !== false;
        if (shouldDebounce) {
            this.debouncedUpdateHints = debounce(this.updateHints.bind(this), 30);
        } else {
            this.debouncedUpdateHints = this.updateHints.bind(this);
        }
    }

    destroy() {
        super.destroy();
        this.clearHints();
    }

    normalize() {
        this.clearHints();
        this.updateHints();
    }

    triggerDebouncedUpdateHints(
        selectionData = this.dependencies.selection.getSelectionData(),
    ) {
        if (selectionData.documentSelectionIsInEditable) {
            this.clearHints();
        }
        this.debouncedUpdateHints();
    }

    updateHints() {
        const selectionData = this.dependencies.selection.getSelectionData();
        const editableSelection = selectionData.editableSelection;
        this.clearHints();
        if (editableSelection.isCollapsed) {
            const hints = this.getResource("hints");
            for (const provideTargets of this.getResource("hint_targets_providers")) {
                for (const target of provideTargets(selectionData, this.editable)) {
                    const nodeHint = hints.find((h) =>
                        target.matches(h.selector),
                    )?.text;
                    if (target && nodeHint && this.shouldDisplayHint(target)) {
                        this.makeHint(target, nodeHint);
                    }
                }
            }
        }
    }

    shouldDisplayHint(el) {
        let shouldDisplay =
            isEmptyBlock(el) && !isProtected(el) && !descendants(el).some(isEditorTab);
        if (shouldDisplay && el.childNodes.length) {
            // A hint is drawn on the block's own line height. If the caret sits
            // in an inline with another font size, the two do not line up and
            // the hint would overlap the text, so drop it.
            const hintFontSize = parseInt(getComputedStyle(el).fontSize);
            const childFontSize = parseInt(
                getComputedStyle(firstLeaf(el).parentElement).fontSize,
            );
            shouldDisplay = childFontSize === hintFontSize;
        }
        return shouldDisplay;
    }

    makeHint(el, text) {
        this.dispatchTo("make_hint_handlers", el);
        el.setAttribute("o-we-hint-text", text);
        el.classList.add("o-we-hint");
    }

    removeHint(el) {
        el.removeAttribute("o-we-hint-text");
        removeClass(el, "o-we-hint");
        this.getResource("system_style_properties").forEach((n) =>
            el.style.removeProperty(n),
        );
    }

    clearHints(root = this.editable) {
        for (const elem of selectElements(root, ".o-we-hint")) {
            this.removeHint(elem);
        }
    }
}
