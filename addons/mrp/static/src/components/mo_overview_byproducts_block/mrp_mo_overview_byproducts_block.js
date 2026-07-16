/** @odoo-module native */
import { MoOverviewLine } from "../mo_overview_line/mrp_mo_overview_line.js";
import { MoOverviewOperationsBlock } from "../mo_overview_operations_block/mrp_mo_overview_operations_block.js";

export class MoOverviewByproductsBlock extends MoOverviewOperationsBlock {
    static components = {
        MoOverviewLine,
    };
    // Reuse the operations block props, minus "operations", plus "byproducts".
    // The "summary" prop is rebuilt (fresh object + fresh shape) rather than
    // mutated in place: it is shared by reference with MoOverviewOperationsBlock.props,
    // so mutating it would leak "product_cost" into the operations block's schema.
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

    //---- Getters ----

    get hasByproducts() {
        return this.props?.byproducts?.length > 0;
    }

    get level() {
        return this.hasByproducts ? this.props.byproducts[0].level - 1 : 0;
    }
}
