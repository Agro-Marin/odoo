/** @odoo-module native */
import { onMounted } from "@odoo/owl";
import { useLayoutEffect } from "@web/core/utils/layout_effect";
import { browser } from "@web/core/browser/browser";
import { router } from "@web/core/browser/router";
import { ControlPanel } from "@web/search/control_panel/control_panel";
import { useService, useEventBus } from "@web/core/utils/hooks";
import { useViewConfig } from "@web/core/view_config_hooks";

export class TodoFormControlPanel extends ControlPanel {
    static template = "project_todo.TodoFormControlPanel";

    setup() {
        super.setup();
        this.bus = useEventBus();
        this.config = useViewConfig();
        this.ui = useService("ui");
        useLayoutEffect(
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
        this.bus.trigger("TODO:TOGGLE_CHATTER", {
            displayChatter: this.state.displayChatter,
        });
    }
}
