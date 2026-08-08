// @ts-check
/** @odoo-module native */

/** @module @web/fields/selection/selection_like_field */

import { Component } from "@odoo/owl";
import { Domain } from "@web/core/domain";
import { useSpecialData } from "@web/fields/relational/special_data";
import { getFieldDomain } from "@web/model/relational_model/utils";

export class SelectionLikeField extends Component {
    /** Only assigned when {@link type} is `"many2one"`. @type {{ data: [number, string][] }} */
    specialData;

    setup() {
        this.type = this.props.record.fields[this.props.name].type;
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
                return this.props.record.data[this.props.name]
                    ? this.props.record.data[this.props.name].display_name
                    : "";
            case "selection":
                return this.props.record.data[this.props.name] !== false
                    ? /** @type {any} */ (
                          this.props.record.fields[this.props.name].selection.find(
                              (/** @type {any} */ o) =>
                                  o[0] === this.props.record.data[this.props.name],
                          )?.[1] ?? ""
                      )
                    : "";
            default:
                return "";
        }
    }

    get value() {
        const rawValue = this.props.record.data[this.props.name];
        return this.type === "many2one" && rawValue ? rawValue.id : rawValue;
    }

    stringify(/** @type {any} */ value) {
        return JSON.stringify(value);
    }
}
