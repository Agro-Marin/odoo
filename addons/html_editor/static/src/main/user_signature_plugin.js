/** @odoo-module native */
import { isHtmlContentSupported } from "@html_editor/core/selection_plugin";
import { Plugin } from "@html_editor/plugin";
import {
    isEmptyBlock,
    paragraphRelatedElementsSelector,
} from "@html_editor/utils/dom_info";
import { withSequence } from "@html_editor/utils/resource";
import { markup } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";
import { renderToElement } from "@web/core/utils/render";

export const SIGNATURE_CLASS = "o-signature-container";

export class UserSignaturePlugin extends Plugin {
    static id = "userSignature";
    static dependencies = ["dom", "history", "selection"];
    static shared = ["cleanSignatures"];
    /** @type {import("plugins").EditorResources} */
    resources = {
        user_commands: [
            {
                id: "insertUserSignature",
                title: _t("Signature"),
                description: _t("Insert your email signature"),
                icon: "fa-pencil-square-o",
                run: this.insertUserSignature.bind(this),
                isAvailable: isHtmlContentSupported,
            },
        ],
        powerbox_categories: withSequence(100, {
            id: "basic_block",
            name: _t("Basic Block"),
        }),
        powerbox_items: [
            {
                categoryId: "basic_block",
                commandId: "insertUserSignature",
            },
        ],

        /** Predicates */
        is_empty_predicates: this.isEmpty.bind(this),
        unsplittable_node_predicates: (node) =>
            node.nodeType === Node.ELEMENT_NODE &&
            node.matches(`.${SIGNATURE_CLASS}`),
    };

    /**
     * Strip the signature blocks out of a clone of the editable, so a caller
     * can read the content without them.
     *
     * @param {Object} param
     * @param {Element} param.rootClone
     */
    cleanSignatures({ rootClone }) {
        for (const el of rootClone.querySelectorAll(`.${SIGNATURE_CLASS}`)) {
            el.remove();
        }
    }

    async insertUserSignature() {
        const [currentUser] = await this.services.orm.read(
            "res.users",
            [user.userId],
            ["signature"],
        );
        if (!currentUser?.signature) {
            return;
        }
        const signature = markup(currentUser.signature);
        const signatureBlock = renderToElement("html_editor.Signature", {
            signature: markup`<br>-- <br>${signature}`,
            signatureClass: SIGNATURE_CLASS,
        });
        this.dependencies.dom.insert(signatureBlock);
        const lastPhrasingElement = [
            ...signatureBlock.querySelectorAll(paragraphRelatedElementsSelector),
        ].at(-1);
        this.dependencies.selection.setCursorEnd(
            lastPhrasingElement || signatureBlock,
        );
        this.dependencies.history.addStep();
    }

    isEmpty(element) {
        if (
            element.nodeType === Node.ELEMENT_NODE &&
            element.matches(`.${SIGNATURE_CLASS}`) &&
            isEmptyBlock(element)
        ) {
            return true;
        }
    }
}
