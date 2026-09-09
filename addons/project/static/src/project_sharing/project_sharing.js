/** @odoo-module native */
import { Component, onMounted, useExternalListener, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { useOwnDebugContext } from "@web/core/debug/debug_context";
import { useBus, useService } from "@web/core/utils/hooks";
import { MainComponentsContainer } from "@web/ui/main_components_container";
import { ActionContainer } from "@web/webclient/actions";

export class ProjectSharingWebClient extends Component {
    static props = {};
    static components = { ActionContainer, MainComponentsContainer };
    static template = "project.ProjectSharingWebClient";

    setup() {
        this.actionService = useService("action");
        useOwnDebugContext({ categories: ["default"] });
        this.state = useState({
            fullscreen: false,
        });
        useBus(this.env.bus, "ACTION_MANAGER:UI-UPDATED", (mode) => {
            if (mode !== "new") {
                this.state.fullscreen = mode === "fullscreen";
            }
        });
        onMounted(() => {
            this.loadRouterState();
            this.env.bus.trigger("WEB_CLIENT_READY");
        });
        useExternalListener(window, "click", this.onGlobalClick, { capture: true });
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
                } catch {
                }
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
