// @ts-check
/** @odoo-module native */

import { Component, onMounted } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { provideChildViewConfig } from "@web/core/view_config_hooks";
import { ControlPanel } from "@web/search/control_panel/control_panel";

export class BlankComponent extends Component {
    static props = ["onMounted", "withControlPanel", "*"];
    static template = "web.BlankComponent";
    static components = { ControlPanel };

    setup() {
        this.ui = useService("ui");
        provideChildViewConfig({ breadcrumbs: [], noBreadcrumbs: true });
        onMounted(() => this.props.onMounted());
    }
}
