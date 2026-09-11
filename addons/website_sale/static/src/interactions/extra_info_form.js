/** @odoo-module native */
import { patch } from "@web/core/utils/patch";
import { patchDynamicContent } from "@web/public/utils";
import { Form } from "@website/snippets/s_website_form/form";

patch(Form.prototype, {
    setup() {
        super.setup();
        if (this.el.dataset.force_action === "shop.sale.order") {
            this.dynamicSelectors = {
                ...this.dynamicSelectors,
                _submitbuttons: () =>
                    document.querySelectorAll('[name="website_sale_main_button"]'),
            };
            patchDynamicContent(this.dynamicContent, {
                _submitbuttons: {
                    "t-on-click.prevent.stop": this.locked(this.send.bind(this), true),
                },
            });
        }
    },
});
