/** @odoo-module native */
import { Component, useState } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { _t } from "@web/core/translation";
import { Dialog } from "@web/ui/dialog";
const log = makeLogger("pos.popup.selection");
export class SelectionPopup extends Component {
    static template = "point_of_sale.SelectionPopup";
    static components = { Dialog };
    static props = {
        title: { type: String, optional: true },
        list: { type: Array, optional: true },
        getPayload: Function,
        close: Function,
        size: { type: String, optional: true },
    };
    static defaultProps = {
        title: _t("Select"),
        list: [],
        size: "lg",
    };

    /**
     * @param {Object} props
     * @param {String} [props.title='Select']
     * @param {Array<Selection>} [props.list=[]]
     */
    setup() {
        this.state = useState({
            selectedId: this.props.list.find((item) => item.isSelected)?.id,
        });
    }
    selectItem(itemId) {
        this.state.selectedId = itemId;
        this.confirm();
    }
    computePayload() {
        const selected = this.props.list.find(
            (item) => this.state.selectedId === item.id,
        );
        return selected && selected.item;
    }
    confirm() {
        log.logic("confirm", () => ({
            title: this.props.title,
            options: this.props.list.length,
            selected: this.state.selectedId,
        }));
        this.props.getPayload(this.computePayload());
        this.props.close();
    }
}
