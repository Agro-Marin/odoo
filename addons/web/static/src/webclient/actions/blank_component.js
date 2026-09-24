// @ts-check
/** @odoo-module native */

import { Component, onMounted, useChildSubEnv } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { ControlPanel } from "@web/search/control_panel/control_panel";

export class BlankComponent extends Component {
    static props = ["onMounted", "withControlPanel", "*"];
    static template = "web.BlankComponent";
    static components = { ControlPanel };

    setup() {
        this.ui = useService("ui");
        useChildSubEnv({ config: { breadcrumbs: [], noBreadcrumbs: true } });
        onMounted(() => this.props.onMounted());
    }
}
