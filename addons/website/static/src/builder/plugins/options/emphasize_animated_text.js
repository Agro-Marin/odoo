/** @odoo-module native */
import { useBuilderContext } from "@html_builder/core/builder_context";
import { Component, useState } from "@odoo/owl";
import { CheckBox } from "@web/components/checkbox";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { useBus } from "@web/core/utils/hooks";

const log = makeLogger("website.builder.option.emphasize_animated_text");

export class EmphasizeAnimatedText extends Component {
    static template = "website.EmphasizeAnimatedText";
    static components = { CheckBox };
    static props = [];

    setup() {
        this.builderContext = useBuilderContext();
        useLifecycleLog(log);
        this.state = useState({
            animatedTextEmphasized: this.isAnimatedTextEmphasized(),
            hasAnimatedText: this.hasAnimatedText(),
        });
        useBus(this.builderContext.editorBus, "DOM_UPDATED", (ev) => {
            this.state.hasAnimatedText = this.hasAnimatedText();
        });
    }

    toggleEmphasizeAnimatedText() {
        this.state.animatedTextEmphasized =
            this.builderContext.editor.document.body.classList.toggle(
                "o_animated_text_emphasized",
            );
        log.logic("EmphasizeAnimatedText toggle", () => ({
            emphasized: this.builderContext.editor.document.body.classList.contains(
                "o_animated_text_emphasized",
            ),
        }));
    }

    isAnimatedTextEmphasized() {
        return !!this.builderContext.editor.document.body.classList.contains(
            "o_animated_text_emphasized",
        );
    }

    hasAnimatedText() {
        return !!this.builderContext.editor.editable.querySelector(".o_animated_text");
    }
}
