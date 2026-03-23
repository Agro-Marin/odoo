/** @odoo-module native */
import { MoOverviewOperationsBlock } from "../mo_overview_operations_block/mrp_mo_overview_operations_block.js";
import { MoOverviewLine } from "../mo_overview_line/mrp_mo_overview_line.js";

export class MoOverviewByproductsBlock extends MoOverviewOperationsBlock {
    static components = {
        MoOverviewLine,
    };
    static props = {
        // Keep all props except "operations"
        ...(({ operations, ...props }) => props)(MoOverviewOperationsBlock.props),
        byproducts: Array,
    };

    static template = "mrp.MoOverviewByproductsBlock";

    //---- Getters ----

    get hasByproducts() {
        return this.props?.byproducts?.length > 0;
    }

    get level() {
        return this.hasByproducts ? this.props.byproducts[0].level - 1 : 0;
    }
}
MoOverviewByproductsBlock.props.summary.shape = {
    ...MoOverviewByproductsBlock.props.summary.shape,
    product_cost: { type: Number, optional: true },
};
