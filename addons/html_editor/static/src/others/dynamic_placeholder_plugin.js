/** @odoo-module native */
import { isHtmlContentSupported } from "@html_editor/core/selection_plugin";
import { Plugin } from "@html_editor/plugin";
import { withSequence } from "@html_editor/utils/resource";
import { _t } from "@web/core/translation";
import { DynamicPlaceholderPopover } from "@web/fields/dynamic_placeholder_popover";
import {
    buildQwebPlaceholder,
    placeholderExpression,
    resolveTzPath,
} from "@web/fields/dynamic_placeholder_syntax";

/**
 * @typedef {Object} DynamicPlaceholderShared
 * @property {DynamicPlaceholderPlugin['updateDphDefaultModel']} updateDphDefaultModel
 */

export class DynamicPlaceholderPlugin extends Plugin {
    static id = "dynamicPlaceholder";
    static dependencies = ["overlay", "selection", "history", "dom"];
    static shared = ["updateDphDefaultModel"];
    /** @type {import("plugins").EditorResources} */
    resources = {
        user_commands: [
            {
                id: "openDynamicPlaceholder",
                title: _t("Dynamic Placeholder"),
                description: _t("Insert a field"),
                icon: "fa-hashtag",
                run: (params = {}) =>
                    this.open(params.resModel || this.defaultResModel),
                isAvailable: isHtmlContentSupported,
            },
        ],
        powerbox_categories: withSequence(60, {
            id: "marketing_tools",
            name: _t("Marketing Tools"),
        }),
        powerbox_items: {
            categoryId: "marketing_tools",
            commandId: "openDynamicPlaceholder",
        },
        power_buttons: { commandId: "openDynamicPlaceholder" },
    };
    setup() {
        this.defaultResModel = this.config.dynamicPlaceholderResModel;

        /** @type {import("@html_editor/core/overlay_plugin").Overlay} */
        this.overlay = this.dependencies.overlay.createOverlay(
            DynamicPlaceholderPopover,
            {
                hasAutofocus: true,
                className: "popover",
            },
        );
    }

    /**
     * @param {string} resModel
     */
    updateDphDefaultModel(resModel) {
        this.defaultResModel = resModel;
    }

    /**
     * @param {string} resModel
     */
    open(resModel) {
        if (!resModel) {
            return this.services.notification.add(
                _t(
                    "You need to select a model before opening the dynamic placeholder selector.",
                ),
                { type: "danger" },
            );
        }
        // Remembered so that `onValidate` resolves the timezone against the
        // model the picker actually offered, not against whatever the editor
        // was last configured with.
        this.openedResModel = resModel;
        this.overlay.open({
            props: {
                close: this.onClose.bind(this),
                validate: this.onValidate.bind(this),
                resModel: resModel,
                expressionFor: (path, fieldDef) =>
                    placeholderExpression(path, { fieldType: fieldDef?.type }),
            },
        });
    }

    /**
     * @param {string} chain
     * @param {string} defaultValue
     * @param {string} fieldType
     */
    async onValidate(chain, defaultValue, fieldType) {
        if (!chain) {
            return;
        }
        const resModel = this.openedResModel || this.defaultResModel;
        const tzPath =
            fieldType === "datetime"
                ? await resolveTzPath(this.services.orm, resModel)
                : undefined;
        // The default is the element body, which QWeb emits when the value is
        // falsy. Folding it into the expression as `or '...'` said the same
        // thing in a second grammar, and needed its own quote escaping.
        const { expression, body } = buildQwebPlaceholder({
            path: chain,
            fieldType,
            defaultValue,
            tzPath,
        });

        const t = document.createElement("T");
        t.setAttribute("t-out", expression);
        if (body) {
            t.innerText = body;
        }

        this.dependencies.dom.insert(t);
        this.dependencies.history.addStep();
    }

    onClose() {
        this.overlay.close();
        this.dependencies.selection.focusEditable();
    }
}
