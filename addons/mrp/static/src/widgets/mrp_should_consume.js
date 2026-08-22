/** @odoo-module native */
import { onMounted, onPatched, useRef, useState } from "@odoo/owl";
import { formatFieldFloat } from "@web/core/formatters";
import { registry } from "@web/core/registry";
import { FloatField, floatField } from "@web/fields/basic/float/float_field";

export class MrpShouldConsumeOwl extends FloatField {
    static template = "mrp.ShouldConsume";
    setup() {
        super.setup();
        this.fields = this.props.record.fields;
        this.record = useState(this.props.record);
        this.displayShouldConsume = !["done", "draft", "cancel"].includes(
            this.record.data.state,
        );
        this.inputSpanRef = useRef("numpadDecimal");
        onMounted(this._renderPrefix);
        onPatched(this._renderPrefix);
    }

    _renderPrefix() {
        if (this.displayShouldConsume && this.inputSpanRef.el) {
            this.inputSpanRef.el.classList.add(
                "o_quick_editable",
                "o_field_widget",
                "o_field_number",
                "o_field_float",
            );
        }
    }

    get shouldConsumeQty() {
        return formatFieldFloat(this.record.data.should_consume_qty, {
            ...this.fields.should_consume_qty,
            ...this.nodeOptions,
        });
    }
}

export const mrpShouldConsumeOwl = {
    ...floatField,
    component: MrpShouldConsumeOwl,
    displayName: "MRP Should Consume",
};

registry.category("fields").add("mrp_should_consume", mrpShouldConsumeOwl);
