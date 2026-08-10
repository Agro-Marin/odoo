// @ts-check
/** @odoo-module native */

/** @module @web/fields/selection/selection_like_field */

import { Component } from "@odoo/owl";
import { Domain } from "@web/core/domain";
import { fieldHandle } from "@web/fields/field_handle";
import { useSpecialData } from "@web/fields/relational/special_data";
import { getFieldDomain } from "@web/model/relational_model/utils";

export class SelectionLikeField extends Component {
    /** @returns {import("@web/fields/field_handle").FieldHandle} */
    get field() {
        return fieldHandle(this);
    }

    /** Only assigned when {@link type} is `"many2one"`. @type {{ data: [number, string][] }} */
    specialData;

    setup() {
        this.type = this.field.type;
        if (this.type === "many2one") {
            this.specialData = useSpecialData((orm, props) => {
                const { relation } = props.record.fields[props.name];
                let domain = getFieldDomain(props.record, props.name, props.domain);
                const value = props.record.data[props.name];
                if (domain.length && value) {
                    domain = Domain.or([[["id", "=", value.id]], domain]).toList(
                        props.record.evalContext,
                    );
                }
                return orm.call(relation, "name_search", ["", domain], {
                    context: props.context || {},
                });
            });
        }
    }

    get string() {
        switch (this.type) {
            case "many2one":
                return this.field.value ? this.field.value.display_name : "";
            case "selection":
                return this.field.value !== false
                    ? /** @type {any} */ (
                          this.field.definition.selection.find(
                              (/** @type {any} */ o) => o[0] === this.field.value,
                          )?.[1] ?? ""
                      )
                    : "";
            default:
                return "";
        }
    }

    get value() {
        const rawValue = this.field.value;
        return this.type === "many2one" && rawValue ? rawValue.id : rawValue;
    }

    stringify(/** @type {any} */ value) {
        return JSON.stringify(value);
    }
}
