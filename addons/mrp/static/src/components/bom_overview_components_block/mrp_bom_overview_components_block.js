/** @odoo-module native */
import { Component, onWillUnmount, onWillUpdateProps, useState } from "@odoo/owl";
import { useBus } from "@web/core/utils/hooks";

import { BomOverviewExtraBlock } from "../bom_overview_extra_block/mrp_bom_overview_extra_block.js";
import { BomOverviewLine } from "../bom_overview_line/mrp_bom_overview_line.js";
import { FOLD_ALL, FOLD_CHANGED } from "../overview_fold.js";

export class BomOverviewComponentsBlock extends Component {
    static template = "mrp.BomOverviewComponentsBlock";
    static components = {
        BomOverviewLine,
        BomOverviewComponentsBlock,
        BomOverviewExtraBlock,
    };
    static props = {
        unfoldAll: { type: Boolean, optional: true },
        showOptions: Object,
        currentWarehouseId: { type: Number, optional: true },
        data: Object,
        precision: Number,
    };
    static defaultProps = {
        unfoldAll: false,
    };

    setup() {
        const childFoldstate = this.childIds.reduce(
            (prev, curr) => ({ ...prev, [curr]: !this.props.unfoldAll }),
            {},
        );
        this.state = useState({
            ...childFoldstate,
            unfoldAll: this.props.unfoldAll || false,
        });
        if (this.props.unfoldAll) {
            this.env.overviewBus.trigger(FOLD_CHANGED, {
                ids: this.childIds,
                folded: false,
            });
        }

        if (this.hasComponents) {
            useBus(this.env.overviewBus, FOLD_ALL, ({ detail }) =>
                this.setFoldAll(detail.folded),
            );
        }

        onWillUpdateProps((newProps) => {
            if (this.data.product_id !== newProps.data.product_id) {
                this.childIds.forEach((id) => delete this.state[id]);
                const newChildIds = this.getHasComponents(newProps.data)
                    ? newProps.data.components.map((c) => this.getIdentifier(c))
                    : [];
                newChildIds.forEach((id) => (this.state[id] = true));
                this.state.unfoldAll = false;
            }
        });

        onWillUnmount(() => {
            if (this.hasComponents) {
                this.env.overviewBus.trigger(FOLD_CHANGED, {
                    ids: this.childIds,
                    folded: true,
                });
            }
        });
    }
    //---- Handlers ----

    onToggleFolded(foldId) {
        const newState = !this.state[foldId];
        this.state[foldId] = newState;
        this.state.unfoldAll = false;
        this.env.overviewBus.trigger(FOLD_CHANGED, { ids: [foldId], folded: newState });
    }

    setFoldAll(folded) {
        const allChildIds = this.childIds;
        this.state.unfoldAll = !folded;
        allChildIds.forEach((id) => (this.state[id] = folded));
        this.env.overviewBus.trigger(FOLD_CHANGED, { ids: allChildIds, folded });
    }

    //---- Getters ----

    get data() {
        return this.props.data;
    }

    get hasComponents() {
        return this.getHasComponents(this.data);
    }

    get childIds() {
        return this.hasComponents
            ? this.data.components.map((c) => this.getIdentifier(c))
            : [];
    }

    get identifier() {
        return this.getIdentifier(this.data);
    }

    //---- Utils ----

    getHasComponents(data) {
        return data.components && data.components.length > 0;
    }

    getIdentifier(data, type = null) {
        return `${type ? type : data.type}_${data.index}`;
    }
}
