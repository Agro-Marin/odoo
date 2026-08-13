/** @odoo-module native */
import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { ControlPanel } from "@web/search/control_panel/control_panel";
import { View } from "@web/views/view";
import { standardActionServiceProps } from "@web/webclient/actions";

import { ForecastedButtons } from "./forecasted_buttons.js";
import { ForecastedDetails } from "./forecasted_details.js";
import { ForecastedHeader } from "./forecasted_header.js";
import { ForecastedWarehouseFilter } from "./forecasted_warehouse_filter.js";

export class StockForecasted extends Component {
    static template = "stock.Forecasted";
    static components = {
        ControlPanel,
        ForecastedButtons,
        ForecastedWarehouseFilter,
        ForecastedHeader,
        View,
        ForecastedDetails,
    };
    static props = { ...standardActionServiceProps };
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        this.context = useState(this.props.action.context);
        this.resModel = this.context.active_model;
        this.title = this.props.action.name || _t("Forecasted Report");
        if (!this.context.active_id) {
            this.context.active_id = this.props.action.params.active_id;
            this._reloading = true;
            this.reloadReport();
        }
        this.productId = this.context.active_id;
        this.warehouses = useState([]);

        onWillStart(this._getReportValues);
    }

    async _getReportValues() {
        if (this._reloading) {
            return;
        }
        await this._getResModel();
        const isTemplate = !this.resModel || this.resModel === "product.template";
        this.reportModelName = `stock.forecasted_product_${isTemplate ? "template" : "product"}`;
        this.warehouses.splice(0, this.warehouses.length);
        this.warehouses.push(
            ...(await this.orm.searchRead(
                "stock.warehouse",
                [],
                ["id", "name", "code"],
            )),
        );
        if (!this.context.warehouse_id && this.warehouses.length) {
            this.updateWarehouse(this.warehouses[0].id);
        }
        const reportValues = await this.orm.call(
            this.reportModelName,
            "get_report_values",
            [],
            {
                context: this.context,
                docids: [this.productId],
            },
        );
        this.docs = {
            ...reportValues.docs,
            precision: reportValues.precision,
        };
    }

    async _getResModel() {
        this.resModel = this.context.active_model || this.context.params?.active_model;
        if (!this.resModel) {
            let resModel = this.props.action.res_model;
            if (resModel) {
                if (/^\d+$/.test(resModel)) {
                    const actionModel = await this.orm.read(
                        "ir.model",
                        [Number(resModel)],
                        ["model"],
                    );
                    resModel = actionModel[0]?.model;
                }
                this.resModel = resModel;
            } else if (this.props.action._originalAction) {
                try {
                    const originalContext = JSON.parse(
                        this.props.action._originalAction,
                    ).context;
                    if (typeof originalContext === "string") {
                        this.resModel = originalContext.match(
                            /active_model['"]?\s*:\s*['"]([\w.]+)['"]/,
                        )?.[1];
                    } else if (originalContext) {
                        this.resModel = originalContext.active_model;
                    }
                } catch {}
            }
            this.context.active_model = this.resModel;
        }
    }

    async updateWarehouse(id) {
        const hasPreviousValue = this.context.warehouse_id !== undefined;
        this.context.warehouse_id = id;
        if (hasPreviousValue) {
            await this.reloadReport();
        }
    }

    async reloadReport() {
        const actionRequest = {
            id: this.props.action.id,
            type: "ir.actions.client",
            tag: "stock_forecasted",
            context: this.context,
            name: this.title,
        };
        const options = { stackPosition: "replaceCurrentAction" };
        return this.action.doAction(actionRequest, options);
    }

    get graphDomain() {
        const domain = [
            ["state", "=", "forecast"],
            ["warehouse_id", "=", this.context.warehouse_id],
        ];
        if (this.resModel === "product.template") {
            domain.push(["product_tmpl_id", "=", this.productId]);
        } else if (this.resModel === "product.product") {
            domain.push(["product_id", "=", this.productId]);
        }
        return domain;
    }

    get graphInfo() {
        return { noContentHelp: _t("Try to add some incoming or outgoing transfers.") };
    }

    async openView(resModel, view, resId = false, domain = false) {
        const views = [[false, view]];
        if (view !== "form") {
            views.push([false, "form"]);
        }
        const action = {
            type: "ir.actions.act_window",
            res_model: resModel,
            views,
            view_mode: view,
            res_id: resId,
            domain: domain,
        };
        return this.action.doAction(action);
    }
}

registry.category("actions").add("stock_forecasted", StockForecasted);
