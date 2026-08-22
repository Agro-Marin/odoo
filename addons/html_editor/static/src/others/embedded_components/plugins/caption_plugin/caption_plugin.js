/** @odoo-module native */
import { isHtmlContentSupported } from "@html_editor/core/selection_plugin";
import { Plugin } from "@html_editor/plugin";
import { closestBlock, isBlock } from "@html_editor/utils/blocks";
import { unwrapContents } from "@html_editor/utils/dom";
import {
    EDITABLE_MEDIA_CLASS,
    isParagraphRelatedElement,
    isVisible,
} from "@html_editor/utils/dom_info";
import { closestElement } from "@html_editor/utils/dom_traversal";
import { boundariesOut, rightPos } from "@html_editor/utils/position";
import { findInSelection } from "@html_editor/utils/selection";
import { _t } from "@web/core/translation";
import { renderToElement } from "@web/core/utils/render";

export class CaptionPlugin extends Plugin {
    static id = "caption";
    static dependencies = [
        "image",
        "split",
        "history",
        "embeddedComponents",
        "selection",
        "baseContainer",
    ];
    /** @type {import("plugins").EditorResources} */
    resources = {
        user_commands: [
            {
                id: "toggleImageCaption",
                title: _t("Add/remove a caption"),
                run: this.toggleImageCaption.bind(this),
                isAvailable: isHtmlContentSupported,
            },
        ],
        toolbar_items: [
            {
                id: "image_caption",
                description: _t("Add/remove a caption"),
                groupId: "image_description",
                commandId: "toggleImageCaption",
                text: _t("Caption"),
                isActive: () =>
                    this.hasImageCaption(this.dependencies.image.getTargetedImage()),
            },
        ],
        clean_for_save_handlers: this.cleanForSave.bind(this),
        mount_component_handlers: this.setupNewCaption.bind(this),
        delete_handlers: this.afterDelete.bind(this),
        before_cut_handlers: this.expandSelectionToCaption.bind(this),
        before_drag_handlers: this.expandSelectionToCaption.bind(this),
        delete_image_overrides: this.handleDeleteImage.bind(this),
        after_save_media_dialog_handlers: this.onImageReplaced.bind(this),
        hints: [{ selector: "FIGCAPTION", text: _t("Write a caption...") }],
        unsplittable_node_predicates: [
            (node) => ["FIGURE", "FIGCAPTION"].includes(node.nodeName),
        ],
        image_name_predicates: [this.getImageName.bind(this)],
        link_compatible_selection_predicates: this.isLinkAllowedOnSelection.bind(this),
        empty_node_predicates: (el) =>
            el.matches?.("figure") &&
            el.children.length === 1 &&
            el.children[0].matches("figcaption"),
        move_node_whitelist_selectors: "figure",

        clipboard_content_processors: this.processContentForClipboard.bind(this),
    };

    setup() {
        for (const figure of this.editable.querySelectorAll("figure")) {
            const image = figure.querySelector("img");
            figure.before(image);
            const caption = figure.querySelector("figcaption")?.textContent;
            figure.remove();
            this.addImageCaption(image, caption, false);
            this.dependencies.history.addStep();
        }
    }

    cleanForSave({ root }) {
        for (const figure of root.querySelectorAll("figure")) {
            figure.removeAttribute("contenteditable");
            const image = figure.querySelector("img");
            figure.querySelector("figcaption").remove();
            const caption = root.ownerDocument.createElement("figcaption");
            caption.textContent = image.getAttribute("data-caption");
            image.removeAttribute("data-caption");
            image.removeAttribute("data-caption-id");
            image.classList.remove(EDITABLE_MEDIA_CLASS);
            image.after(caption);
        }
    }

    hasImageCaption(image) {
        if (!image) {
            return;
        }
        const block = closestBlock(image.parentElement);
        return (
            block.nodeName === "FIGURE" &&
            !!block.querySelector("[data-embedded='caption'] input")
        );
    }

    toggleImageCaption(image = this.dependencies.image.getTargetedImage()) {
        if (!image) {
            return;
        }
        if (this.hasImageCaption(image)) {
            this.removeImageCaption(image);
        } else {
            this.addImageCaption(image, image.getAttribute("data-caption") || "");
            this.dependencies.history.addStep();
        }
    }

    getCaptionId() {
        return "" + Math.floor(Math.random() * Date.now());
    }

    addImageCaption(image, captionText = "", focusInput = true) {
        const figure = this.document.createElement("figure");
        const link = image.parentElement.nodeName === "A" && image.parentElement;
        const target = link || image;
        const blockEl = closestBlock(target.parentElement);
        if (
            (target.nextSibling || target.previousSibling) &&
            isParagraphRelatedElement(blockEl)
        ) {
            const block = this.dependencies.split.splitAroundUntil(target, blockEl);
            if (isBlock(block.previousSibling) && !isVisible(block.previousSibling)) {
                block.previousSibling.remove();
            }
            if (isBlock(block.nextSibling) && !isVisible(block.nextSibling)) {
                block.nextSibling.remove();
            }
        }
        image.before(figure);
        figure.append(image);
        if (!link && isParagraphRelatedElement(figure.parentElement)) {
            unwrapContents(figure.parentElement);
            this.dependencies.selection.setCursorEnd(figure);
        }
        const captionId = this.getCaptionId();
        image.setAttribute("data-caption-id", captionId);
        image.setAttribute("data-caption", captionText || "");
        figure.setAttribute("contenteditable", "false");
        image.classList.add(EDITABLE_MEDIA_CLASS);
        const caption = renderToElement("html_editor.EmbeddedCaptionBlueprint", {
            embeddedProps: JSON.stringify({
                id: captionId,
                focusInput,
            }),
        });
        figure.append(caption);
    }

    removeImageCaption(image) {
        const figure = closestElement(image, "figure");
        if (figure) {
            figure.querySelector("figcaption").remove();
            if (!isParagraphRelatedElement(closestBlock(figure.parentElement))) {
                const baseContainer =
                    this.dependencies.baseContainer.createBaseContainer();
                if (figure.parentElement.nodeName === "A") {
                    figure.parentElement.before(baseContainer);
                    baseContainer.append(figure.parentElement);
                } else {
                    figure.before(baseContainer);
                    baseContainer.append(figure);
                }
            }
            unwrapContents(figure);
            image.removeAttribute("data-caption-id");
            image.classList.remove(EDITABLE_MEDIA_CLASS);
            const [anchorNode, anchorOffset, focusNode, focusOffset] =
                boundariesOut(image);
            this.dependencies.selection.setSelection({
                anchorNode,
                anchorOffset,
                focusNode,
                focusOffset,
            });
            this.dependencies.selection.focusEditable();
            this.dependencies.history.addStep();
        }
    }

    setupNewCaption({ name, props }) {
        if (name === "caption") {
            const id = props.id;
            delete props.id;
            const image = this.editable.querySelector(`img[data-caption-id="${id}"]`);
            const previousCaption = image.getAttribute("data-caption");
            Object.assign(props, {
                image,
                onUpdateCaption: (caption = "") => {
                    const figcaption = image.parentElement.querySelector("figcaption");
                    const didCaptionChanged = previousCaption !== caption;
                    if (
                        caption &&
                        figcaption &&
                        figcaption.getAttribute("placeholder") !== caption
                    ) {
                        figcaption.setAttribute("placeholder", caption);
                    }
                    if (didCaptionChanged) {
                        image.setAttribute("data-caption", caption);
                        this.dependencies.history.addStep();
                    }
                },
                onEditorHistoryApply: (redo = false) => {
                    if (redo) {
                        this.dependencies.history.redo();
                    } else {
                        this.dependencies.history.undo();
                    }
                },
            });
        }
    }

    getImageName(image) {
        if (closestElement(image, "figure")) {
            return image.getAttribute("data-caption");
        }
    }

    isLinkAllowedOnSelection() {
        const figure = findInSelection(
            this.dependencies.selection.getSelectionData().deepEditableSelection,
            "figure",
        );
        if (
            figure &&
            this.dependencies.selection
                .getTargetedNodes()
                .every((node) => closestElement(node, "figure") === figure)
        ) {
            return true;
        }
    }

    onImageReplaced(media) {
        const figure = closestElement(media, "figure");
        let anchorNode, anchorOffset;
        if (figure) {
            if (media.nodeName === "IMG") {
                [anchorNode, anchorOffset] = rightPos(figure);
                const caption = figure.querySelector(
                    "[data-embedded='caption'] input",
                )?.value;
                figure.before(media);
                figure.remove();
                this.addImageCaption(media, caption, false);
            } else {
                this.removeImageCaption(media);
                [anchorNode, anchorOffset] = rightPos(media);
            }
            this.dependencies.selection.setSelection({ anchorNode, anchorOffset });
        }
    }

    afterDelete() {
        const { anchorNode } = this.dependencies.selection.getEditableSelection();
        const targetedNodes = this.dependencies.selection.getTargetedNodes();
        for (const figure of this.editable.querySelectorAll("figure:not(:has(img))")) {
            const isSelectionInFigure =
                targetedNodes.includes(figure) || anchorNode === figure;
            const sibling = figure.nextSibling || figure.previousSibling;
            figure.remove();
            if (isSelectionInFigure) {
                this.dependencies.selection.setSelection({
                    anchorNode: sibling,
                    anchorOffset: 0,
                });
            }
        }
    }

    handleDeleteImage(image) {
        const figure = closestElement(image, "figure");
        if (figure) {
            const sibling = figure.nextSibling || figure.previousSibling;
            figure.remove();
            this.dependencies.selection.setSelection({
                anchorNode: sibling,
                anchorOffset: 0,
            });
            this.dependencies.history.addStep();
            return true;
        }
    }

    expandSelectionToCaption(selection) {
        const startFigure = closestElement(selection.anchorNode, "figure");
        const endFigure = closestElement(selection.focusNode, "figure");

        if (startFigure && startFigure === endFigure) {
            const [anchorNode, anchorOffset, focusNode, focusOffset] =
                boundariesOut(startFigure);
            this.dependencies.selection.setSelection(
                { anchorNode, anchorOffset, focusNode, focusOffset },
                { normalize: false },
            );
        }
    }

    /**
     * @param {DocumentFragment} clonedContents
     * @param {import("@html_editor/core/selection_plugin").EditorSelection} selection
     */
    processContentForClipboard(clonedContents, selection) {
        if (clonedContents.firstChild.nodeName === "IMG") {
            clonedContents = selection.commonAncestorContainer.cloneNode(true);
        }
        return clonedContents;
    }
}
