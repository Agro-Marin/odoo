/** @odoo-module native */
import { registry } from "@web/core/registry";
import { exprToBoolean } from "@web/core/utils/format/strings";
import { booleanFavoriteField } from "@web/fields/basic/boolean_favorite/boolean_favorite_field";

export const projectIsFavoriteField = {
    ...booleanFavoriteField,
    extractProps: (fieldsInfo, dynamicInfo) => {
        return {
            ...booleanFavoriteField.extractProps(fieldsInfo, dynamicInfo),
            // Deliberately ignore dynamicInfo.readonly (the base widget's
            // source): toggling the favorite star must stay possible on
            // readonly views. Only an explicit readonly="..." on the arch
            // disables it — parsed with exprToBoolean, so readonly="0" or
            // readonly="False" is not truthy.
            readonly: exprToBoolean(fieldsInfo.attrs.readonly),
        };
    },
};

registry.category("fields").add("project_is_favorite", projectIsFavoriteField);
