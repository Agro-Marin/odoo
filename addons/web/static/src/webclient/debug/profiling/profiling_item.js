// @ts-check
/** @odoo-module native */

/** @module @web/webclient/debug/profiling/profiling_item - Debug menu dropdown item for toggling SQL/trace profiling collectors */

import { Component, EventBus } from "@odoo/owl";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { useBus, useService } from "@web/core/utils/hooks";
export class ProfilingItem extends Component {
    static components = { DropdownItem };
    static template = "web.DebugMenu.ProfilingItem";
    static props = {
        bus: { type: EventBus },
    };
    setup() {
        this.profiling = useService("profiling");
        // The action service is absent in the frontend bundle, so we cannot
        // useService() unconditionally — it would throw at setup time. Read
        // the raw entry from env.services with optional chaining instead.
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
        // eslint-disable-next-line no-restricted-syntax -- action is optional (absent in frontend bundle); useService would throw on setup
        const action = this.env.services.action;
        if (action) {
            // Preserve breadcrumbs by using the backend action.
            action.doAction("base.action_menu_ir_profile");
        } else {
            /** @type {any} */ (window).location =
                "/web/#action=base.action_menu_ir_profile";
        }
    }
}
