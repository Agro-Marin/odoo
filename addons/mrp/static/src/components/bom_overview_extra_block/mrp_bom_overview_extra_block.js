/** @odoo-module native */
import { useBus } from "@web/core/utils/hooks";
import { BomOverviewLine } from "../bom_overview_line/mrp_bom_overview_line.js";
import { BomOverviewSpecialLine } from "../bom_overview_special_line/mrp_bom_overview_special_line.js";
import { Component, onWillUnmount, onWillUpdateProps, useState } from "@odoo/owl";
import { FOLD_ALL, FOLD_CHANGED } from "../overview_fold.js";

export class BomOverviewExtraBlock extends Component {
    static template = "mrp.BomOverviewExtraBlock";
    static components = {
        BomOverviewLine,
        BomOverviewSpecialLine,
    };
    static props = {
        unfoldAll: { type: Boolean, optional: true },
        type: {
            type: String,
            validate: (t) => ["operations", "byproducts"].includes(t),
        },
        showOptions: Object,
        data: Object,
        precision: Number,
    };

    setup() {
        this.state = useState({
            isFolded: !this.props.unfoldAll,
        });
        if (this.props.unfoldAll) {
            this.env.overviewBus.trigger(FOLD_CHANGED, { ids: [this.identifier], folded: false });
        }

        useBus(this.env.overviewBus, FOLD_ALL, ({ detail }) => this.setFolded(detail.folded));

        onWillUpdateProps(newProps => {
            if (this.props.data.product_id != newProps.data.product_id) {
                this.state.isFolded = true;
            }
        });

        onWillUnmount(() => {
            // Need to notify main component that the block was folded so it doesn't appear on the PDF.
            this.env.overviewBus.trigger(FOLD_CHANGED, { ids: [this.identifier], folded: true });
        });
    }

    //---- Handlers ----

    onToggleFolded() {
        const newState = !this.state.isFolded;
        this.state.isFolded = newState;
        this.env.overviewBus.trigger(FOLD_CHANGED, { ids: [this.identifier], folded: newState });
    }

    setFolded(folded) {
        this.state.isFolded = folded;
        this.env.overviewBus.trigger(FOLD_CHANGED, { ids: [this.identifier], folded });
    }

    //---- Getters ----

    get identifier() {
        return `${this.props.type}_${this.props.data.index}`;
    }
}
