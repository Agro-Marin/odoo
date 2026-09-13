/** @odoo-module native */
import { Component, useRef } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { WebsiteDialog } from "@website/components/dialog/dialog";

const log = makeLogger("website.builder.translation.select_translate_dialog");

export class SelectTranslateDialog extends Component {
    static components = { WebsiteDialog };
    static template = "website_builder.SelectTranslateDialog";
    static props = {
        node: { validate: (p) => p.nodeType === Node.ELEMENT_NODE },
        addStep: Function,
        close: Function,
    };
    setup() {
        useLifecycleLog(log);
        this.inputEl = useRef("input");
    }

    onInputChange() {
        const value = this.inputEl.el.value;
        log.logic("onInputChange", () => ({
            translated: value !== this.props.node.dataset.initialTranslationValue,
        }));
        this.optionEl.textContent = value;
        this.optionEl.classList.toggle(
            "oe_translated",
            value !== this.optionEl.dataset.initialTranslationValue,
        );
    }

    get optionEl() {
        return this.props.node;
    }

    addStepAndClose() {
        log.pipeline("addStepAndClose");
        this.props.addStep();
        this.props.close();
    }
}
