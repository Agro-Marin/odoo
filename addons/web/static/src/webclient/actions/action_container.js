// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_container - Thin OWL wrapper rendering the current action's component inside the action manager div */

import { Component, onWillDestroy, xml } from "@odoo/owl";
import { AppEvent } from "@web/core/events";

/**
 * Thin OWL wrapper that listens for ACTION_MANAGER:UPDATE events on `env.bus`
 * and renders the current action's component inside the `.o_action_manager` div.
 */
export class ActionContainer extends Component {
    static props = {};
    static template = xml`
        <t t-name="web.ActionContainer">
          <div class="o_action_manager">
            <t t-if="info.Component" t-component="info.Component" className="'o_action'" t-props="info.componentProps" t-key="info.id"/>
          </div>
        </t>`;

    setup() {
        /** @type {Record<string, any>} */
        this.info = {};
        /** @param {CustomEvent} event */
        this.onActionManagerUpdate = ({ detail: info }) => {
            this.info = info;
            // startViewTransition can't wrap owl's render() directly — it resolves
            // before the actual DOM patch, so it would snapshot the pre-update UI
            // (it must await the real patch, e.g. a mount deferred).
            this.render();
        };
        this.env.bus.addEventListener(
            AppEvent.ACTION_MANAGER_UPDATE,
            this.onActionManagerUpdate,
        );
        onWillDestroy(() => {
            this.env.bus.removeEventListener(
                AppEvent.ACTION_MANAGER_UPDATE,
                this.onActionManagerUpdate,
            );
        });
    }
}
