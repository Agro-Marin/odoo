/** @odoo-module native */
import { Component, onMounted, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { provideDebugContext } from "@web/core/debug/debug_context";
import { useBus, useEventBus, useService } from "@web/core/utils/hooks";
import { useListener } from "@web/core/utils/owl_bridge";
import { MainComponentsContainer } from "@web/ui/main_components_container";
import { ActionContainer } from "@web/webclient/actions";

export class ProjectSharingWebClient extends Component {
    static props = {};
    static components = { ActionContainer, MainComponentsContainer };
    static template = "project.ProjectSharingWebClient";

    setup() {
        this.bus = useEventBus();
        this.actionService = useService("action");
        provideDebugContext({ categories: ["default"] });
        this.state = useState({
            fullscreen: false,
        });
        useBus(this.bus, "ACTION_MANAGER:UI-UPDATED", (mode) => {
            if (mode !== "new") {
                this.state.fullscreen = mode === "fullscreen";
            }
        });
        onMounted(() => {
            this.loadRouterState();
            this.bus.trigger("WEB_CLIENT_READY");
        });
        useListener(window, "click", this.onGlobalClick.bind(this), { capture: true });
    }

    async loadRouterState() {
        const stateLoaded = await this.actionService.loadState();

        if (stateLoaded) {
            if (browser.location.hash !== "") {
                try {
                    const el = document.querySelector(browser.location.hash);
                    if (el !== null) {
                        el.scrollIntoView(true);
                    }
                } catch {}
            }
        }
    }

    /** @param {MouseEvent} ev */
    onGlobalClick(ev) {
        if (
            (ev.ctrlKey || ev.metaKey) &&
            !ev.target.isContentEditable &&
            ((ev.target instanceof HTMLAnchorElement && ev.target.href) ||
                (ev.target instanceof HTMLElement &&
                    ev.target.closest("a[href]:not([href=''])")))
        ) {
            ev.stopImmediatePropagation();
            return;
        }
    }
}
