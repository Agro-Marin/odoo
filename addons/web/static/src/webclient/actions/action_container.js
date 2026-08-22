// @ts-check
/** @odoo-module native */

import { Component, onWillDestroy, xml } from "@odoo/owl";
import { AppEvent } from "@web/core/events";

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
