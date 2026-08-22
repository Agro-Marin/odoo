/** @odoo-module native */
import { MoOverviewLine } from "../mo_overview_line/mrp_mo_overview_line.js";
import { MoOverviewOperationsBlock } from "../mo_overview_operations_block/mrp_mo_overview_operations_block.js";

export class MoOverviewByproductsBlock extends MoOverviewOperationsBlock {
    static components = {
        MoOverviewLine,
    };
    static props = (() => {
        const { summary } = MoOverviewOperationsBlock.props;
        const props = { ...MoOverviewOperationsBlock.props };
        delete props.operations;
        props.summary = {
            ...summary,
            shape: { ...summary.shape, product_cost: { type: Number, optional: true } },
        };
        props.byproducts = Array;
        return props;
    })();

    static template = "mrp.MoOverviewByproductsBlock";

    get hasByproducts() {
        return this.props?.byproducts?.length > 0;
    }

    get level() {
        return this.hasByproducts ? this.props.byproducts[0].level - 1 : 0;
    }
}
