// @ts-check
/** @odoo-module native */

import { Component, EventBus } from "@odoo/owl";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { useBus, useService } from "@web/core/utils/hooks";
export class ProfilingItem extends Component {
    static components = { DropdownItem };
    static template = "web.DebugMenu.ProfilingItem";
    static props = {
        bus: { type: EventBus },
    };
    /** @type {import("services").ServiceFactories["action"]} */
    action;
    /** @type {import("services").ServiceFactories["profiling"]} */
    profiling;

    setup() {
        this.profiling = useService("profiling");
        this.action = useService("action");
        useBus(this.props.bus, "UPDATE", /** @type {any} */ (this.render));
    }

    changeParam(param, ev) {
        this.profiling.setParam(param, ev.target.value);
    }
    toggleParam(param) {
        const value = this.profiling.state.params[param];
        this.profiling.setParam(param, !value);
    }
    openProfiles() {
        this.action.doAction("base.action_menu_ir_profile");
    }
}
