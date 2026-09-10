// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";
import { fieldVisualFeedback } from "@web/fields/field";
import { getTooltipInfo } from "@web/fields/field_tooltip";

/**
 * A label's tooltip payload depends on the field definition, the arch's field
 * info and the debug flag, none of which change for the life of a form, so it
 * is serialised once per label rather than on every render.
 * @type {WeakMap<Object, { field: Object, debug: string, info: string }>}
 */
const tooltipInfoByFieldInfo = new WeakMap();

export class FormLabel extends Component {
    static template = "web.FormLabel";
    static props = {
        fieldInfo: { type: Object },
        record: { type: Object },
        fieldName: { type: String },
        className: { type: String, optional: true },
        string: { type: String },
        id: { type: String },
        notMuttedLabel: { type: Boolean, optional: true },
    };

    /** @returns {string} */
    get className() {
        const { invalid, empty, readonly } = fieldVisualFeedback(
            this.props.fieldInfo.field,
            this.props.record,
            this.props.fieldName,
            this.props.fieldInfo,
        );
        const classes = this.props.className ? [this.props.className] : [];
        if (invalid) {
            classes.push("o_field_invalid");
        }
        if (empty) {
            classes.push("o_form_label_empty");
        }
        if (readonly && !this.props.notMuttedLabel) {
            classes.push("o_form_label_readonly");
        }
        return classes.join(" ");
    }

    /** @returns {boolean} */
    get hasTooltip() {
        return Boolean(odoo.debug || this.tooltipHelp);
    }

    /** @returns {string} */
    get tooltipHelp() {
        const field = this.props.record.fields[this.props.fieldName];
        let help = this.props.fieldInfo.help || field.help || "";
        if (field.company_dependent && user.allowedCompanies.length > 1) {
            help += (help ? "\n\n" : "") + _t("Values set here are company-specific.");
        }
        return help;
    }
    /** @returns {string} */
    get tooltipInfo() {
        const { fieldInfo, record, fieldName } = this.props;
        const field = record.fields[fieldName];
        const cached = tooltipInfoByFieldInfo.get(fieldInfo);
        if (cached && cached.field === field && cached.debug === odoo.debug) {
            return cached.info;
        }
        const info = odoo.debug
            ? getTooltipInfo({
                  viewMode: "form",
                  resModel: record.resModel,
                  field,
                  fieldInfo,
                  help: this.tooltipHelp,
              })
            : JSON.stringify({ field: { help: this.tooltipHelp } });
        tooltipInfoByFieldInfo.set(fieldInfo, { field, debug: odoo.debug, info });
        return info;
    }
}
