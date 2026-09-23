// @ts-check
/** @odoo-module native */

import { Component, EventBus, useState } from "@odoo/owl";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { useService } from "@web/core/utils/hooks";

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
        this.state = useState(this.profiling.state);
    }

    changeParam(param, ev) {
        this.profiling.setParam(param, ev.target.value);
    }
    /** @param {string} collector */
    isCollectorEnabled(collector) {
        return this.state.collectors.includes(collector);
    }

    toggleParam(param) {
        const value = this.profiling.state.params[param];
        this.profiling.setParam(param, !value);
    }
    openProfiles() {
        this.action.doAction("base.action_menu_ir_profile");
    }
}
