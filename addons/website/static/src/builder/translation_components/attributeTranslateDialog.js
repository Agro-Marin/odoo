/** @odoo-module native */
import { Component } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { WebsiteDialog } from "@website/components/dialog/dialog";

const log = makeLogger("website.builder.translation.attribute_translate_dialog");

export class AttributeTranslateDialog extends Component {
    static components = { WebsiteDialog };
    static template = "website_builder.AttributeTranslateDialog";
    static props = {
        node: { validate: (p) => p.nodeType === Node.ELEMENT_NODE },
        elToTranslationInfoMap: Object,
        addStep: Function,
        applyCustomMutation: Function,
        close: Function,
    };

    setup() {
        useLifecycleLog(log);
        this.modifiedAttrs = {};
    }

    onInputChange(ev) {
        const inputEl = ev.target;
        const attr = inputEl.previousSibling.textContent;
        const translateEl = this.props.node;
        const newValue = inputEl.value;
        this.modifiedAttrs[attr] = newValue;
        log.logic("onInputChange", { attr, isTextContent: attr === "textContent" });
        if (attr !== "textContent") {
            translateEl.setAttribute(attr, newValue);
            if (attr === "value") {
                translateEl.value = newValue;
            }
        } else {
            translateEl.value = newValue;
        }
        translateEl.classList.add("oe_translated");
    }

    get translationInfos() {
        return this.props.elToTranslationInfoMap.get(this.props.node);
    }

    addStepAndClose() {
        const oldValue = JSON.parse(JSON.stringify(this.translationInfos));
        log.pipeline("addStepAndClose: apply attribute translations", () => ({
            modified: Object.keys(this.modifiedAttrs),
        }));
        this.props.applyCustomMutation({
            apply: () => {
                for (const [attr, newValue] of Object.entries(this.modifiedAttrs)) {
                    this.translationInfos[attr].translation = newValue;
                }
            },
            revert: () => {
                for (const attr of Object.keys(this.modifiedAttrs)) {
                    this.translationInfos[attr].translation =
                        oldValue[attr].translation;
                }
            },
        });
        this.props.addStep();
        this.props.close();
    }
}
