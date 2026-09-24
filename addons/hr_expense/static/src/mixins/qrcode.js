/** @odoo-module native */
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { onMounted, onPatched, useRef } from "@odoo/owl";

export const ExpenseMobileQRCode = (T) =>
    class ExpenseMobileQRCode extends T {
        setup() {
            super.setup();
            this.ui = useService("ui");
            this.root = useRef("root");
            this.actionService = useService("action");

            onMounted(this.bindAppsIcons);
            onPatched(this.bindAppsIcons);
        }

        bindAppsIcons() {
            const apps = this.root.el.querySelectorAll(".o_expense_mobile_app");
            if (!apps) {
                return;
            }

            const handler = this.handleClick.bind(this);
            for (const app of apps) {
                app.addEventListener("click", handler);
            }
        }

        handleClick(ev) {
            ev.preventDefault();
            ev.stopPropagation();

            const url = ev.currentTarget && ev.currentTarget.href;
            if (!this.ui.isSmall) {
                this.actionService.doAction({
                    name: _t("Download our App"),
                    type: "ir.actions.client",
                    tag: "expense_qr_code_modal",
                    target: "new",
                    params: { url },
                });
            } else {
                this.actionService.doAction({ type: "ir.actions.act_url", url });
            }
        }
    };
