/** @odoo-module native */
import { Component, EventBus, onWillStart, useState, useSubEnv } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

import { BomOverviewControlPanel } from "../bom_overview_control_panel/mrp_bom_overview_control_panel.js";
import { BomOverviewTable } from "../bom_overview_table/mrp_bom_overview_table.js";
import { FOLD_ALL, useUnfoldedIds } from "../overview_fold.js";

export class BomOverviewComponent extends Component {
    static template = "mrp.BomOverviewComponent";
    static components = {
        BomOverviewControlPanel,
        BomOverviewTable,
    };
    static props = { ...standardActionServiceProps };
    setup() {
        this.orm = useService("orm");
        this.context = this.props.action.context;
        this.actionService = useService("action");

        this.variants = [];
        this.warehouses = [];
        this.showVariants = false;
        this.uomName = "";

        this.state = useState({
            showOptions: {
                mode: this.props.action.context.mode || "overview",
                uom: false,
                attachments: false,
            },
            currentWarehouse: null,
            currentVariantId: null,
            bomData: {},
            precision: 2,
            bomQuantity: null,
            foldable: true,
            allFolded: true,
        });

        useSubEnv({
            overviewBus: new EventBus(),
        });
        // Kept in sync (via the shared fold protocol) with the folded rows so the
        // printed PDF reproduces the on-screen state.
        this.unfoldedIds = useUnfoldedIds();

        useBus(
            this.env.overviewBus,
            FOLD_ALL,
            ({ detail }) => (this.state.allFolded = detail.folded),
        );

        onWillStart(async () => {
            await this.getWarehouses();
            await this.initBomData();
        });
    }

    //---- Data ----

    async initBomData() {
        const variantId = this.props.action.context.active_product_id;
        const resModel = this.props.action.context.active_model;
        this.state.currentVariantId = false;
        if (resModel === "product.product" && variantId !== undefined) {
            this.state.currentVariantId = variantId;
        }

        const bomData = await this.getBomData();
        this.state.bomQuantity = bomData["bom_qty"];
        this.state.showOptions.uom = bomData["is_uom_applied"];
        this.uomName = bomData["bom_uom_name"];
        this.variants = bomData["variants"];
        this.showVariants = bomData["is_variant_applied"];
        if (this.showVariants) {
            this.state.currentVariantId ||= this.state.bomData.product_id;
        }
        this.state.precision = bomData["precision"];
        this.state.foldable = bomData["lines"]["foldable"];
    }

    async getBomData() {
        const args = [
            this.activeId,
            this.state.bomQuantity,
            this.state.currentVariantId,
        ];
        const context = { ...this.context };
        if (this.state.currentWarehouse) {
            context.warehouse_id = this.state.currentWarehouse.id;
        }
        const bomData = await this.orm.call(
            "report.mrp.report_bom_structure",
            "get_html",
            args,
            { context },
        );
        this.state.bomData = bomData["lines"];
        this.state.showOptions.attachments = bomData["has_attachments"];
        return bomData;
    }

    async getWarehouses() {
        const warehouses = await this.orm.call(
            "report.mrp.report_bom_structure",
            "get_warehouses",
        );
        this.warehouses = warehouses;
        this.state.currentWarehouse = warehouses[0];
    }

    //---- Handlers ----

    onChangeMode(mode) {
        this.state.showOptions.mode = mode;
    }

    async onChangeBomQuantity(newQuantity) {
        if (this.state.bomQuantity !== newQuantity) {
            this.state.bomQuantity = newQuantity;
            await this.getBomData();
        }
    }

    async onChangeVariant(variantId) {
        if (this.state.currentVariantId !== variantId) {
            this.state.currentVariantId = variantId;
            await this.getBomData();
        }
    }

    async onChangeWarehouse(warehouseId) {
        if (this.state.currentWarehouse.id !== warehouseId) {
            this.state.currentWarehouse = this.warehouses.find(
                (wh) => wh.id === warehouseId,
            );
            await this.getBomData();
        }
    }

    async onClickPrint(printAll) {
        return this.actionService.doAction({
            type: "ir.actions.report",
            report_type: "qweb-pdf",
            report_name: this.getReportName(printAll),
            report_file: "mrp.report_bom_structure",
        });
    }

    //---- Getters ----

    get activeId() {
        return this.props.action.context.active_id;
    }

    // ---- Helpers ----

    getReportName(printAll) {
        const params = new URLSearchParams({
            docids: this.activeId,
            mode: this.state.showOptions.mode,
            quantity: this.state.bomQuantity || 1,
            unfolded_ids: JSON.stringify(Array.from(this.unfoldedIds)),
        });
        if (this.state.currentWarehouse) {
            params.set("warehouse_id", this.state.currentWarehouse.id);
        }
        if (printAll) {
            params.set("all_variants", 1);
        } else if (this.showVariants && this.state.currentVariantId) {
            params.set("variant", this.state.currentVariantId);
        }
        return `mrp.report_bom_structure?${params}`;
    }
}

registry.category("actions").add("mrp_bom_report", BomOverviewComponent);
