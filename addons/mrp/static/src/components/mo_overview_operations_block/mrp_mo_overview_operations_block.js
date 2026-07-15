/** @odoo-module native */
import { Component, useState } from "@odoo/owl";
import { useBus } from "@web/core/utils/hooks";
import { formatFloat, formatFloatTime, formatMonetary } from "@web/fields/formatters";
import { MoOverviewLine } from "../mo_overview_line/mrp_mo_overview_line.js";
import { getColorClass } from "../mrp_overview_utils.js";
import { SHOW_OPTIONS } from "../mo_overview_display_filter/mrp_mo_overview_display_filter.js";
import { FOLD_ALL, FOLD_CHANGED } from "../overview_fold.js";

export class MoOverviewOperationsBlock extends Component {
    static template = "mrp.MoOverviewOperationsBlock";
    static components = {
        MoOverviewLine,
    };
    static props = {
        unfoldAll: { type: Boolean, optional: true },
        operations: Array,
        summary: {
            type: Object,
            shape: {
                index: String,
                quantity: { type: Number, optional: true },
                quantity_decorator: { type: [String, Boolean], optional: true },
                mo_cost: { type: Number, optional: true },
                mo_cost_decorator: { type: [String, Boolean], optional: true },
                bom_cost: { type: [Number, Boolean], optional: true },
                real_cost: { type: Number, optional: true },
                real_cost_decorator: { type: [String, Boolean], optional: true },
                uom_name: { type: String, optional: true },
                currency_id: { type: Number, optional: true },
                currency: { type: String, optional: true },
                done: { type: Boolean, optional: true },
            },
        },
        showOptions: SHOW_OPTIONS,
    };
    static defaultProps = {
        unfoldAll: false,
    };

    setup() {
        this.formatFloatTime = formatFloatTime;
        this.getColorClass = getColorClass;
        this.state = useState({
            // Unfold the main MO's operations by default
            isFolded: this.level > 0 && !this.props.unfoldAll,
        });
        if (this.props.unfoldAll) {
            this.env.overviewBus.trigger(FOLD_CHANGED, { ids: [this.index], folded: false });
        }

        useBus(this.env.overviewBus, FOLD_ALL, ({ detail }) => this.setFolded(detail.folded));
    }

    //---- Handlers ----

    toggleFolded() {
        this.state.isFolded = !this.state.isFolded;
        this.env.overviewBus.trigger(FOLD_CHANGED, { ids: [this.index], folded: this.state.isFolded });
    }

    setFolded(folded) {
        this.state.isFolded = folded;
        this.env.overviewBus.trigger(FOLD_CHANGED, { ids: [this.index], folded });
    }

    //---- Helpers ----

    formatMonetary(val) {
        return formatMonetary(val, { currencyId: this.props.summary.currency_id });
    }

    //---- Getters ----

    get hasOperations() {
        return this.props?.operations?.length > 0;
    }

    get level() {
        return this.hasOperations ? this.props.operations[0].level - 1 : 0;
    }

    get index() {
        return this.props.summary.index;
    }

    get totalQuantity() {
        // Float for Hours when displaying done productions, FloatTime for Minutes otherwise.
        return this.props.summary?.done ?
            formatFloat(this.props.summary.quantity, { digits: [false, this.props.operations[0].uom_precision || undefined] }) :
            formatFloatTime(this.props.summary.quantity)
    }
}
