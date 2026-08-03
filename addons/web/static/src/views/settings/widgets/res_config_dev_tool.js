// @ts-check
/** @odoo-module native */

/** @module @web/views/settings/widgets/res_config_dev_tool */

import { Component, onWillStart } from "@odoo/owl";
import { useAction } from "@web/core/action_port";
import { router } from "@web/core/browser/router";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Setting } from "@web/views/form/setting/setting";
import { SettingsBlock } from "@web/views/settings/settings/settings_block";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

export class ResConfigDevTool extends Component {
    static template = "res_config_dev_tool";
    static components = {
        SettingsBlock,
        Setting,
    };
    static props = {
        ...standardWidgetProps,
    };

    /** @type {import("@web/core/action_port").ActionPort} */
    action;
    /** @type {import("services").ServiceFactories["demo_data"]} */
    demo;

    setup() {
        /** @type {boolean} */
        this.isDebug = Boolean(odoo.debug);
        this.isAssets = odoo.debug.includes("assets");
        this.isTests = odoo.debug.includes("tests");

        this.action = useAction();
        this.demo = useService("demo_data");

        onWillStart(async () => {
            this.isDemoDataActive = await this.demo.isDemoDataActive();
        });
    }

    /**
     * @param {string} value
     */
    activateDebug(value) {
        router.pushState({ debug: value }, { reload: true });
    }

    onClickForceDemo() {
        this.action.doAction("base.demo_force_install_action");
    }
}

/** @type {import("registries").ViewWidgetsRegistryItemShape} */
export const resConfigDevTool = {
    component: ResConfigDevTool,
};

registry.category("view_widgets").add("res_config_dev_tool", resConfigDevTool);
