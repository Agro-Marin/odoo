/** @odoo-module native */
import { useService } from '@web/core/utils/hooks';
import { ActionContainer } from "@web/webclient/actions";
import { MainComponentsContainer } from "@web/ui/main_components_container";
import { useOwnDebugContext } from "@web/core/debug/debug_context";
import { session } from '@web/session';
import { Component, useEffect, useExternalListener } from "@odoo/owl";

export class SubcontractingPortalWebClient extends Component {
    static components = { ActionContainer, MainComponentsContainer };
    static template = "mrp_subcontracting.SubcontractingPortalWebClient";
    static props = {};
    setup() {
        window.parent.document.body.style.margin = "0";
        this.actionService = useService('action');
        useOwnDebugContext({ categories: ["default"] });
        useEffect(
            () => {
                this._showView();
            },
            () => []
        );
        useExternalListener(window, "click", this.onGlobalClick, { capture: true });
    }

    async _showView() {
        const { action_name, picking_id } = session;
        await this.actionService.doAction(
            action_name,
            {
                props: {
                    resId: picking_id,
                    preventEdit: true,
                    preventCreate: true,
                },
                additionalContext: {
                    no_breadcrumbs: true,
                }
            }
        );
    }

    /**
     * @param {MouseEvent} ev
     */
     onGlobalClick(ev) {
        if (
            ev.ctrlKey &&
            ((ev.target instanceof HTMLAnchorElement && ev.target.href) ||
                (ev.target instanceof HTMLElement && ev.target.closest("a[href]:not([href=''])")))
        ) {
            ev.stopImmediatePropagation();
            return;
        }
    }
}
