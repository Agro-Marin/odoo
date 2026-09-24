/** @odoo-module native */
import { onMounted, useEffect } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { router } from "@web/core/browser/router";
import { ControlPanel } from "@web/search/control_panel/control_panel";
import { useService } from "@web/core/utils/hooks";
import { useViewConfig } from "@web/core/view_config_hooks";

export class TodoFormControlPanel extends ControlPanel {
    static template = "project_todo.TodoFormControlPanel";

    setup() {
        super.setup();
        this.config = useViewConfig();
        this.ui = useService("ui");
        useEffect(
            (isSmall) => {
                if (isSmall && !this.state.displayChatter) {
                    this.toggleChatter();
                }
            },
            () => [this.ui.isSmall],
        );
        onMounted(() => {
            const isFromActivityView =
                router.current.actionStack?.[router.current.actionStack?.length - 1]
                    ?.view_type === "activity";
            if (
                !this.ui.isSmall &&
                !this.state.displayChatter &&
                (isFromActivityView ||
                    JSON.parse(browser.localStorage.getItem("isChatterOpened")))
            ) {
                this.toggleChatter();
            }
        });
    }

    toggleChatter(ev) {
        this.state.displayChatter = !this.state.displayChatter;
        if (ev) {
            browser.localStorage.setItem("isChatterOpened", this.state.displayChatter);
        }
        this.env.bus.trigger("TODO:TOGGLE_CHATTER", {
            displayChatter: this.state.displayChatter,
        });
    }
}
