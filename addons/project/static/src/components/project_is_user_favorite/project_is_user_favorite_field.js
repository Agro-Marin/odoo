/** @odoo-module native */
import { registry } from "@web/core/registry";
import { exprToBoolean } from "@web/core/utils/format/strings";
import { booleanFavoriteField } from "@web/fields/basic/boolean_favorite/boolean_favorite_field";

export const projectIsUserFavoriteField = {
    ...booleanFavoriteField,
    extractProps: (fieldsInfo, dynamicInfo) => ({
        ...booleanFavoriteField.extractProps(fieldsInfo, dynamicInfo),
        readonly: exprToBoolean(fieldsInfo.attrs.readonly),
    }),
};

registry.category("fields").add("project_is_user_favorite", projectIsUserFavoriteField);
