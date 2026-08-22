/** @odoo-module native */
import { selectElements } from "@html_editor/utils/dom_traversal";

import { Plugin } from "../plugin.js";

import DOMPurify from "dompurify";

/**
 * @typedef { Object } SanitizeShared
 * @property { SanitizePlugin['sanitize'] } sanitize
 */

export class SanitizePlugin extends Plugin {
    static id = "sanitize";
    static shared = ["sanitize"];
    /** @type {import("plugins").EditorResources} */
    resources = {
        clean_for_save_handlers: this.cleanForSave.bind(this),
        normalize_handlers: this.normalize.bind(this),
    };

    setup() {
        this.DOMPurify = DOMPurify(this.window);
    }
    /**
     * @param {HTMLElement} elem
     * @returns {HTMLElement}
     */
    sanitize(elem) {
        for (const cb of this.getResource("before_sanitize_processors")) {
            elem = cb(elem);
        }
        elem = this.DOMPurify.sanitize(elem, {
            IN_PLACE: true,
            ADD_TAGS: ["#document-fragment", "fake-el"],
            ADD_ATTR: ["contenteditable", "t-field", "t-out", "t-esc"],
        });
        for (const cb of this.getResource("after_sanitize_processors")) {
            elem = cb(elem);
        }
        return elem;
    }

    normalize(element) {
        for (const el of selectElements(
            element,
            ".o-contenteditable-false, .o-contenteditable-true",
        )) {
            el.contentEditable = el.matches(".o-contenteditable-true");
        }
        for (const el of selectElements(element, "[data-oe-role]")) {
            el.setAttribute("role", el.dataset.oeRole);
        }
        for (const el of selectElements(element, "[data-oe-aria-label]")) {
            el.setAttribute("aria-label", el.dataset.oeAriaLabel);
        }
    }

    cleanForSave({ root }) {
        for (const el of selectElements(
            root,
            ".o-contenteditable-false, .o-contenteditable-true",
        )) {
            el.removeAttribute("contenteditable");
        }
        for (const el of selectElements(root, "[data-oe-role]")) {
            el.removeAttribute("role");
        }
        for (const el of selectElements(root, "[data-oe-aria-label]")) {
            el.removeAttribute("aria-label");
        }
    }
}
