/** @odoo-module native */
import { useBuilderContext } from "@html_builder/core/builder_context";
import { useOperation } from "@html_builder/core/operation_plugin";
import { useDomState } from "@html_builder/core/utils";
import { Component } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";

const log = makeLogger("website.builder.option.navtabs_header_buttons");

export class NavTabsHeaderMiddleButtons extends Component {
    static template = "website.NavTabsHeaderMiddleButtons";
    static props = {
        addItem: Function,
        removeItem: Function,
    };

    setup() {
        this.builderContext = useBuilderContext();
        useLifecycleLog(log);
        this.state = useDomState((editingElement) => {
            const navEl = editingElement.querySelector(".nav");
            return {
                tabEls: navEl.querySelectorAll(".nav-item"),
            };
        });

        this.callOperation = useOperation();
    }

    addItem() {
        this.callOperation(async () => {
            const endAddItem = log.perf("NavTabsHeaderMiddleButtons addItem");
            await this.props.addItem(this.builderContext.getEditingElement());
            endAddItem();
        });
    }

    removeItem() {
        this.callOperation(() => {
            log.pipeline("NavTabsHeaderMiddleButtons removeItem");
            this.props.removeItem(this.builderContext.getEditingElement());
        });
    }
}
