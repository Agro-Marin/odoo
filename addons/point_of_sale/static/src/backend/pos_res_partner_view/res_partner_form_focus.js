/** @odoo-module native */
import { onMounted } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { FormRenderer } from "@web/views/form/form_renderer";

/**
 * The POS partner form is opened with a field prefilled from the search term
 * (see `PosStore.editPartnerContext`). `default_focus` names that field so the
 * cashier lands on it and can keep typing.
 */
patch(FormRenderer.prototype, {
    setup() {
        super.setup();

        onMounted(() => {
            const fieldName = this.props.record?.context?.default_focus;
            if (!fieldName) {
                return;
            }
            const input = document.querySelector(`[name="${fieldName}"] input`);
            input?.focus();
        });
    },
});
