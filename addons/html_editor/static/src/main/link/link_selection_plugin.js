/** @odoo-module native */
import { Plugin } from "@html_editor/plugin";
import { removeClass } from "@html_editor/utils/dom";
import { isProtected, isProtecting } from "@html_editor/utils/dom_info";
import { closestElement, selectElements } from "@html_editor/utils/dom_traversal";

/**
 * @typedef { Object } LinkSelectionShared
 * @property { LinkSelectionPlugin['padLinkWithZwnbsp'] } padLinkWithZwnbsp
 */

/**
 * @typedef {((link: HTMLLinkElement) => boolean)[]} ineligible_link_for_selection_indication_predicates
 * @typedef {((link: HTMLLinkElement) => boolean)[]} ineligible_link_for_zwnbsp_predicates
 */

export class LinkSelectionPlugin extends Plugin {
    static id = "linkSelection";
    static dependencies = ["selection", "feff"];
    static shared = ["padLinkWithZwnbsp"];
    /** @type {import("plugins").EditorResources} */
    resources = {
        selectionchange_handlers: this.resetLinkInSelection.bind(this),
        clean_for_save_handlers: ({ root }) => this.clearLinkInSelectionClass(root),
        normalize_handlers: () => this.resetLinkInSelection(),
        feff_providers: this.addFeffsToLinks.bind(this),
        system_classes: ["o_link_in_selection"],
    };

    addFeffsToLinks(root, cursors) {
        return [...selectElements(root, "a")]
            .filter(this.isLinkEligibleForZwnbsp.bind(this))
            .flatMap((link) => this.dependencies.feff.surroundWithFeffs(link, cursors));
    }

    /**
     * @param {HTMLAnchorElement} link
     */
    padLinkWithZwnbsp(link) {
        const cursors = this.dependencies.selection.preserveSelection();
        this.dependencies.feff.surroundWithFeffs(link, cursors);
        cursors.restore();
    }

    isLinkEligibleForZwnbsp(link) {
        const { anchorNode, focusNode } =
            this.dependencies.selection.getEditableSelection();
        const isLinkSelected = link.contains(anchorNode) || link.contains(focusNode);
        const linkHasContentOrSelected =
            isLinkSelected || link.textContent.replaceAll("\ufeff", "");
        return (
            linkHasContentOrSelected &&
            link.isContentEditable &&
            link.parentElement.isContentEditable &&
            this.editable.contains(link) &&
            !isProtected(link) &&
            !isProtecting(link) &&
            !this.getResource("ineligible_link_for_zwnbsp_predicates").some((p) =>
                p(link),
            )
        );
    }

    isLinkEligibleForVisualIndication(link) {
        return (
            this.isLinkEligibleForZwnbsp(link) &&
            !this.getResource(
                "ineligible_link_for_selection_indication_predicates",
            ).some((predicate) => predicate(link))
        );
    }

    /**
     * @param {SelectionData} [selectionData]
     */
    resetLinkInSelection(
        selectionData = this.dependencies.selection.getSelectionData(),
    ) {
        this.clearLinkInSelectionClass(this.editable);

        const { anchorNode, focusNode } = selectionData.editableSelection;
        const [anchorLink, focusLink] = [anchorNode, focusNode].map((node) =>
            closestElement(node, "a"),
        );
        const singleLinkInSelection = anchorLink === focusLink && anchorLink;

        if (
            singleLinkInSelection &&
            this.isLinkEligibleForVisualIndication(singleLinkInSelection) &&
            this.document.activeElement === this.editable
        ) {
            singleLinkInSelection.classList.add("o_link_in_selection");
        }
    }

    clearLinkInSelectionClass(root) {
        for (const link of selectElements(root, ".o_link_in_selection")) {
            removeClass(link, "o_link_in_selection");
        }
    }
}
