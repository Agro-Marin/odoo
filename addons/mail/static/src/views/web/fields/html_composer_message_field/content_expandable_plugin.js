/** @odoo-module native */
import { Plugin } from "@html_editor/plugin";
import { fillEmpty } from "@html_editor/utils/dom";
import { isEmptyBlock } from "@html_editor/utils/dom_info";
import { closestElement, selectElements } from "@html_editor/utils/dom_traversal";
import { renderToElement } from "@web/core/utils/render";
export class ContentExpandablePlugin extends Plugin {
    static id = "contentexpandable";
    static dependencies = ["protectedNode", "selection"];
    resources = {
        /** @param {{root: HTMLElement}} params */
        clean_for_save_handlers: ({ root }) => this.cleanForSave(root),
        delete_backward_overrides: this.deleteBackward.bind(this),
        move_node_blacklist_selectors:
            ".o_mail_reply_container, .o_mail_reply_container *",
    };

    setup() {
        this.insertReplyContent();
    }

    /**
     * @param {{endContainer: Node}} range
     * @returns {boolean|undefined}
     */
    deleteBackward({ endContainer }) {
        const closestReplyContainer = closestElement(
            endContainer,
            ".o_mail_reply_container",
        );
        if (closestReplyContainer && isEmptyBlock(closestReplyContainer)) {
            const parentEl = closestReplyContainer.parentElement;
            closestReplyContainer.remove();
            fillEmpty(parentEl);
            return true;
        }
    }

    /**
     * @param {Event} ev
     * @returns {boolean|undefined}
     */
    isValidTargetForDomListener(ev) {
        if (
            ev.type === "click" &&
            ev.target &&
            closestElement(ev.target, ".o-mail-Message-viewMore-btn")
        ) {
            return true;
        }
        return super.isValidTargetForDomListener(ev);
    }

    insertReplyContent() {
        const ele = this.editable.querySelector(".o_mail_reply_container");
        if (!ele) {
            return;
        }
        this.dependencies.protectedNode.setProtectingNode(ele, true);
        for (const subEl of ele.querySelectorAll(":scope > .o_mail_reply_content")) {
            this.dependencies.protectedNode.setProtectingNode(subEl, false);
            subEl.classList.add("d-none");
        }
        const mailQuoteElement = ele.querySelectorAll('*[data-o-mail-quote="1"]');
        for (const element of mailQuoteElement) {
            element.removeAttribute("data-o-mail-quote");
            element.removeAttribute("style");
        }
        const buttonTemplate = renderToElement("mail.ExpandableButton");
        const button = buttonTemplate.querySelector(".o-mail-Message-viewMore-btn");
        this.addDomListener(button, "click", this.onClickViewButton);
        ele.prepend(buttonTemplate);
    }

    /** @param {MouseEvent} ev */
    onClickViewButton(ev) {
        const ele = closestElement(ev.target, ".o_mail_reply_container");
        if (!ele) {
            return;
        }
        for (const subEl of ele.querySelectorAll(":scope > .o_mail_reply_content")) {
            subEl.classList.toggle("d-none");
        }
        closestElement(ev.target, ".o-mail-Message-viewMore-container")?.remove();
    }

    /** @param {HTMLElement} root */
    cleanForSave(root) {
        for (const el of selectElements(root, ".o_mail_reply_container")) {
            delete el.dataset.oeProtected;
            for (const subEl of el.querySelectorAll(".o_mail_reply_content")) {
                delete subEl.dataset.oeProtected;
                subEl.classList.remove("d-none");
            }
            el.querySelector(".o-mail-Message-viewMore-container")?.remove();
            el.setAttribute("data-o-mail-quote", "1");
        }
    }
}
