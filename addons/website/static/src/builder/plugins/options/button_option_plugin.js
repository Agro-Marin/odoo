/** @odoo-module native */
import { Plugin } from "@html_editor/plugin";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";

const log = makeLogger("website.builder.plugin.button_option");

const selector = "a.btn";
const exclude = ".s_donation_donate_btn, .s_website_form_send";

const styleClasses = [
    "btn-secondary",
    "btn-fill-primary",
    "btn-fill-secondary",
    "btn-outline-primary",
    "btn-outline-secondary",
];
const sizeClasses = ["btn-sm", "btn-lg"];

class ButtonOptionPlugin extends Plugin {
    static id = "buttonOption";
    /** @type {import("plugins").WebsiteResources} */
    resources = {
        on_cloned_handlers: this.onCloned.bind(this),
        on_snippet_over_dropzone_handlers: this.onSnippetPreview.bind(this),
        on_snippet_out_dropzone_handlers: ({ snippetEl, dragState }) =>
            this.resetPreview(snippetEl, dragState),
        on_snippet_dropped_over_handlers: ({ droppedEl, dragState }) =>
            this.resetPreview(droppedEl, dragState),
        on_snippet_dropped_handlers: this.onSnippetDropped.bind(this),
    };

    onCloned({ cloneEl }) {
        if (cloneEl.matches(selector) && !cloneEl.matches(exclude)) {
            log.logic("ButtonOptionPlugin onCloned: adapt siblings, keep appearance");
            this.adaptButtons(cloneEl, { adaptAppearance: false });
        }
    }

    onSnippetPreview({ snippetEl, dragState }) {
        if (snippetEl.matches(selector) && !snippetEl.matches(exclude)) {
            const dropzoneEl = dragState.currentDropzoneEl;
            if (dropzoneEl.classList.contains("oe_grid_zone")) {
                log.logic("ButtonOptionPlugin preview skipped: grid dropzone");
                return;
            }

            const initialState = this.adaptButtons(snippetEl, {
                isDragAndDropPreview: true,
            });
            dragState.restoreButtonPreview = () => {
                const { isWrapped, previousClassName, nextClassName } = initialState;
                snippetEl.className = initialState.buttonClassName;
                if (previousClassName) {
                    initialState.previousSiblingEl.className = previousClassName;
                    snippetEl.previousSibling.remove();
                }
                if (nextClassName) {
                    initialState.nextSiblingEl.className = nextClassName;
                    snippetEl.nextSibling.remove();
                }
                if (isWrapped) {
                    const wrapperEl = snippetEl.parentElement;
                    dropzoneEl.after(snippetEl);
                    wrapperEl.remove();
                }
            };
        }
    }

    /**
     * @param {HTMLElement} snippetEl
     * @param {Object} dragState
     */
    resetPreview(snippetEl, dragState) {
        if (snippetEl.matches(selector) && !snippetEl.matches(exclude)) {
            if ("restoreButtonPreview" in dragState) {
                log.logic("ButtonOptionPlugin restore drag and drop preview");
                dragState.restoreButtonPreview();
                delete dragState.restoreButtonPreview;
            }
        }
    }

    onSnippetDropped({ snippetEl }) {
        if (snippetEl.matches(selector) && !snippetEl.matches(exclude)) {
            log.logic("ButtonOptionPlugin onSnippetDropped: adapt button");
            this.adaptButtons(snippetEl, {});
        }
    }

    /**
     * @param {HTMLElement} editingElement
     * @returns {Object}
     */
    adaptButtons(
        editingElement,
        { adaptAppearance = true, isDragAndDropPreview = false },
    ) {
        let previousSiblingEl = editingElement.previousElementSibling;
        let nextSiblingEl = editingElement.nextElementSibling;
        if (isDragAndDropPreview) {
            while (previousSiblingEl && previousSiblingEl.matches(".oe_drop_zone")) {
                previousSiblingEl = previousSiblingEl.previousElementSibling;
            }
            while (nextSiblingEl && nextSiblingEl.matches(".oe_drop_zone")) {
                nextSiblingEl = nextSiblingEl.nextElementSibling;
            }
        }

        let siblingButtonEl = null;
        const initialState = { buttonClassName: editingElement.className };
        if (nextSiblingEl?.matches(".btn")) {
            initialState.nextClassName = nextSiblingEl.className;
            nextSiblingEl.classList.add("mb-2");
            editingElement.after(" ");
            siblingButtonEl = nextSiblingEl;
        }
        if (previousSiblingEl?.matches(".btn")) {
            initialState.previousClassName = previousSiblingEl.className;
            previousSiblingEl.classList.add("mb-2");
            editingElement.before(" ");
            siblingButtonEl = previousSiblingEl;
        }
        if (siblingButtonEl) {
            editingElement.classList.add("mb-2");
        }
        if (adaptAppearance) {
            if (siblingButtonEl && !editingElement.matches(".s_custom_button")) {
                const styleClass = styleClasses.find((c) =>
                    siblingButtonEl.classList.contains(c),
                );
                const sizeClass = sizeClasses.find((c) =>
                    siblingButtonEl.classList.contains(c),
                );

                if (styleClass) {
                    editingElement.classList.remove("btn-primary");
                    editingElement.classList.add(styleClass);
                }
                if (sizeClass) {
                    editingElement.classList.add(sizeClass);
                }
                if (siblingButtonEl.classList.contains("rounded-circle")) {
                    editingElement.classList.add("rounded-circle");
                }
            } else if (!siblingButtonEl) {
                const btnContainerEl = editingElement.closest("p");
                if (!btnContainerEl) {
                    const paragraphEl = document.createElement("p");
                    editingElement.parentNode.insertBefore(paragraphEl, editingElement);
                    paragraphEl.appendChild(editingElement);
                    initialState.isWrapped = true;
                }
            }
            editingElement.classList.remove("s_custom_button");
        }
        log.pipeline("ButtonOptionPlugin adaptButtons", () => ({
            adaptAppearance,
            isDragAndDropPreview,
            hasSiblingButton: !!siblingButtonEl,
            isWrapped: !!initialState.isWrapped,
        }));
        return { ...initialState, previousSiblingEl, nextSiblingEl };
    }
}

registry.category("website-plugins").add(ButtonOptionPlugin.id, ButtonOptionPlugin);
