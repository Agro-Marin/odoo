/** @odoo-module native */
import { Component, onWillStart, useState } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets";
const log = makeLogger("pos.backend.payment_providers");
export class PosPaymentProviderCards extends Component {
    static template = "point_of_sale.PosPaymentProviderCards";
    static components = {};
    static props = {
        ...standardWidgetProps,
    };

    setup() {
        super.setup();
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            providers: [],
            disabled: false,
        });

        onWillStart(async () => {
            const endStatus = log.perf("get_provider_status");
            const res = await this.orm.call(
                "pos.payment.method",
                "get_provider_status",
                [providers.map((p) => p[1])],
            );
            endStatus({ asked: providers.length, known: res.state.length });

            this.state.providers = providers
                .filter((prov) =>
                    res.state.some((moduleState) => moduleState.name === prov[1]),
                )
                .map((prov) => {
                    const status = res.state.find((p) => p.name === prov[1]);
                    return Object.assign(
                        {
                            selection: prov[0],
                            provider: prov[2],
                        },
                        status,
                    );
                });
        });
    }

    get config_ids() {
        return this.props.record.evalContext.context.config_ids;
    }

    async installModule(moduleId) {
        const recordSave = await this.props.record.save();
        log.pipeline("installModule", () => ({ moduleId, recordSave }));
        if (!recordSave) {
            return;
        }
        this.state.disabled = true;
        await this.orm
            .call("ir.module.module", "button_immediate_install", [moduleId])
            .then((result) => {
                this.state.disabled = false;
                if (result) {
                    window.location.reload();
                }
            })
            .finally(() => {
                this.state.disabled = false;
            });
    }

    async setupProvider(moduleId) {
        const provider = this.state.providers.find((p) => p.id === moduleId);
        log.logic("setupProvider", () => ({
            moduleId,
            selection: provider?.selection,
        }));
        if (provider) {
            this.props.record.update({
                payment_method_type: "terminal",
                use_payment_terminal: provider.selection,
                name: provider.provider,
            });
        }
    }
}

const providers = [
    ["ingenico", "pos_iot_ingenico", "Ingenico"],
    ["six_iot", "pos_iot_six", "SIX"],
    ["adyen", "pos_adyen", "Adyen"],
    ["mercado_pago", "pos_mercado_pago", "Mercado Pago"],
    ["razorpay", "pos_razorpay", "Razorpay"],
    ["stripe", "pos_stripe", "Stripe"],
    ["viva_com", "pos_viva_com", "Viva.com"],
    ["worldline", "pos_iot_worldline", "Worldline"],
    ["tyro", "pos_tyro", "Tyro"],
    ["pine_labs", "pos_pine_labs", "Pine Labs"],
    ["qfpay", "pos_qfpay", "QFPay"],
    ["dpopay", "pos_dpopay", "DPO Pay"],
    ["mollie", "pos_mollie", "Mollie"],
];

export const PosPaymentProviderCardsParams = {
    component: PosPaymentProviderCards,
};

registry
    .category("view_widgets")
    .add("pos_payment_provider_cards", PosPaymentProviderCardsParams);
