/** @odoo-module native */
import { Component } from "@odoo/owl";

export class TModelInput extends Component {
    static template = "";
    static props = { tModel: Array };
    getValue(tModel = this.props.tModel) {
        const [obj, key] = tModel;
        return obj[key];
    }
    setValue(newValue, tModel = this.props.tModel) {
        const [obj, key] = tModel;
        obj[key] = newValue;
    }
}
