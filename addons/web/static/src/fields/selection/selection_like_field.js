// @ts-check
/** @odoo-module native */

import { Domain } from "@web/core/domain";
import { FieldComponent } from "@web/fields/field_component";
import { fieldHandleFor } from "@web/fields/field_handle";
import { useSpecialData } from "@web/fields/relational/special_data";
import { getFieldDomain } from "@web/model/relational_model";

export class SelectionLikeField extends FieldComponent {
    /** @type {{ data: [number, string][] }} */
    specialData;

    setup() {
        this.type = this.field.type;
        if (this.type === "many2one") {
            this.specialData = useSpecialData((orm, props) => {
                const field = fieldHandleFor(props.record, props.name);
                const { relation } = field.definition;
                let domain = getFieldDomain(props.record, props.name, props.domain);
                const value = field.value;
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

    /** @returns {Array<[any, string]>} the choices a selection-like widget offers, an empty label excluded */
    get options() {
        switch (this.type) {
            case "many2one":
                return this.specialData.data;
            case "selection":
                return this.field.definition.selection.filter(
                    (/** @type {[any, string]} */ option) => option[1] !== "",
                );
            default:
                return [];
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

    /**
     * @param {unknown} id
     * @param {Array<[any, string]>} options
     * @returns {{ id: number, display_name: string } | false | undefined}
     */
    many2oneValueFor(id, options) {
        if (id === false || id === null || id === undefined) {
            return false;
        }
        const option = options.find((option) => option[0] === id);
        return option && { id: option[0], display_name: option[1] };
    }

    stringify(/** @type {any} */ value) {
        return JSON.stringify(value);
    }
}
