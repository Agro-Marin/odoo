// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/blank_component - Placeholder controller shown while the action container recovers from an error */

import { Component, onMounted, useChildSubEnv } from "@odoo/owl";
import { ControlPanel } from "@web/search/control_panel/control_panel";

/**
 * Placeholder shown by the action manager during error recovery and
 * transition states (skeleton view, cleared stack).
 *
 * Lives in its own module rather than beside ``ControllerComponent``: the only
 * consumer is now ``ActionDispatch``'s failure path, and importing it from
 * ``controller_component.js`` would make the dispatch object depend on the
 * component that calls it.
 */
export class BlankComponent extends Component {
    static props = ["onMounted", "withControlPanel", "*"];
    static template = "web.BlankComponent";
    static components = { ControlPanel };

    setup() {
        useChildSubEnv({ config: { breadcrumbs: [], noBreadcrumbs: true } });
        onMounted(() => this.props.onMounted());
    }
}
