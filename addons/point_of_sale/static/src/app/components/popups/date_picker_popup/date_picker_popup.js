/** @odoo-module native */
import { Component, onMounted, useRef, useState } from "@odoo/owl";
import { luxon } from "@web/core/l10n/luxon";
import { _t } from "@web/core/l10n/translation";
import { Dialog } from "@web/ui/dialog/dialog";
export class DatePickerPopup extends Component {
    static template = "point_of_sale.DatePickerPopup";
    static components = { Dialog };
    static props = {
        title: { type: String, optional: true },
        confirmLabel: { type: String, optional: true },
        getPayload: Function,
        close: Function,
    };
    static defaultProps = {
        confirmLabel: _t("Confirm"),
        title: _t("DatePicker"),
    };

    setup() {
        super.setup();
        this.state = useState({ shippingDate: this._today() });
        this.inputRef = useRef("input");
        onMounted(() => this.inputRef.el.focus());
    }
    confirm() {
        this.props.getPayload(
            this.state.shippingDate < this._today()
                ? this._today()
                : this.state.shippingDate,
        );
        this.props.close();
    }
    _today() {
        // Local date, not UTC: toISOString() put evening users west of UTC on
        // tomorrow's date (and early-morning users east of UTC on yesterday's).
        return luxon.DateTime.now().toISODate();
    }
}
