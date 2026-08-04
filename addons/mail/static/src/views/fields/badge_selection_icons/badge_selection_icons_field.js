/** @odoo-module native */
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useSpecialData } from "@web/fields/relational/special_data";
import {
    BadgeSelectionField,
    badgeSelectionField,
} from "@web/fields/selection/badge_selection/badge_selection_field";
import { getFieldDomain } from "@web/model/relational_model/utils";
/**
 * Overrides BadgeSelectionField to insert a FontAwesome icon before each option's
 * title. Many2one only: the related options must carry the icon in the field named
 * by the iconField prop.
 *
 * @typedef {Object} Props
 * @property {String} iconField field storing the icon on the many2one option
 * @property {String} defaultIcon fa icon used when iconField is empty
 */
export class BadgeSelectionWithIconsField extends BadgeSelectionField {
    static props = {
        ...BadgeSelectionField.props,
        iconField: { type: String },
        defaultIcon: { type: String, optional: true, default: "fa-check" },
    };
    static template = "mail.BadgeSelectionIconsField";

    /**
     * @override
     * many2one fields use attribute "specialData" to store information pertaining to many2one relations.
     * As such, this.specialData is used by the inherited BadgeSelectionField to store the Many2one selection options for this field.
     */
    async setup() {
        this.type = this.props.record.fields[this.props.name].type;
        this.specialData = useSpecialData(async (orm, props) => {
            const domain = getFieldDomain(props.record, props.name, props.domain);
            const { relation } = props.record.fields[props.name];
            const ret = await orm.call(relation, "search_read", [], {
                domain: domain,
                fields: ["id", "name", props.iconField],
            });
            return ret.map((opt) => {
                const option = Object.values(opt);
                if (!option[2]) {
                    option[2] = props.defaultIcon;
                }
                return option;
            });
        });
    }
}

export const badgeSelectionWithIconsField = {
    ...badgeSelectionField,
    component: BadgeSelectionWithIconsField,
    supportedTypes: ["many2one"],
    displayName: _t("Badges with Icons"),
    extractProps: (fieldInfo, dynamicInfo) => ({
        ...badgeSelectionField.extractProps(fieldInfo, dynamicInfo),
        iconField: fieldInfo.attrs.iconField,
        defaultIcon: fieldInfo.attrs.defaultIcon,
    }),
};
registry.category("fields").add("selection_badge_icons", badgeSelectionWithIconsField);
