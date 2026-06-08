// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_container - Thin OWL wrapper rendering the current action's component inside the action manager div */

import { Component, onWillDestroy, xml } from "@odoo/owl";

// -----------------------------------------------------------------------------
// ActionContainer (Component)
// -----------------------------------------------------------------------------

/**
 * Thin OWL wrapper that listens for ACTION_MANAGER:UPDATE events on `env.bus`
 * and renders the current action's component inside the `.o_action_manager` div.
 *
 * Controller swaps are wrapped in ``document.startViewTransition`` so that the
 * cross-fade between actions is handled by the browser. Falls through to a
 * plain render when the API is unavailable or the user prefers reduced motion.
 */
export class ActionContainer extends Component {
    static props = {};
    static template = xml`
        <t t-name="web.ActionContainer">
          <div class="o_action_manager">
            <t t-if="info.Component" t-component="info.Component" className="'o_action'" t-props="info.componentProps" t-key="info.id"/>
          </div>
        </t>`;

    /** Subscribe to ACTION_MANAGER:UPDATE events and re-render on each update. */
    setup() {
        /** @type {Record<string, any>} */
        this.info = {};
        /** @param {CustomEvent} event */
        this.onActionManagerUpdate = ({ detail: info }) => {
            this.info = info;
            this._renderWithViewTransition();
        };
        this.env.bus.addEventListener(
            "ACTION_MANAGER:UPDATE",
            this.onActionManagerUpdate,
        );
        onWillDestroy(() => {
            this.env.bus.removeEventListener(
                "ACTION_MANAGER:UPDATE",
                this.onActionManagerUpdate,
            );
        });
    }

    /**
     * Render through the View Transitions API when supported, falling back to
     * a plain render when the API is unavailable or the user has requested
     * reduced motion.
     */
    _renderWithViewTransition() {
        const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
        if (typeof document.startViewTransition === "function" && !reducedMotion) {
            document.startViewTransition(() => this.render());
        } else {
            this.render();
        }
    }
}
