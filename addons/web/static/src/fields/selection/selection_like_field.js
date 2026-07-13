// @ts-check
/** @odoo-module native */

/** @module @web/fields/selection/selection_like_field - Abstract base class for selection-like fields with special data loading */

import { Component } from "@odoo/owl";
import { Domain } from "@web/core/domain";
import { useSpecialData } from "@web/fields/relational/special_data";
import { getFieldDomain } from "@web/model/relational_model/utils";

/**
 * Base class for selection-like fields that can target either a `selection`
 * or a `many2one` ORM field type (badge, radio, plain selection).
 *
 * Provides:
 *   - type detection in `setup()`
 *   - `useSpecialData` for many2one options loaded via `name_search`
 *   - `get string()`, `get value()`, `stringify()` — identical across subclasses
 *
 * Subclasses must implement:
 *   - static template
 *   - static props
 *   - onChange()
 *   - their own option-list accessor for their template (`get options()` for
 *     SelectionField/BadgeSelectionField, `get items()` for RadioField). The
 *     base class deliberately does NOT depend on it — `get string()` resolves
 *     labels from the field's `selection` metadata directly.
 */
export class SelectionLikeField extends Component {
    setup() {
        this.type = this.props.record.fields[this.props.name].type;
        if (this.type === "many2one") {
            this.specialData = useSpecialData((orm, props) => {
                const { relation } = props.record.fields[props.name];
                let domain = getFieldDomain(props.record, props.name, props.domain);
                const value = props.record.data[props.name];
                if (domain.length && value) {
                    // OR-in the current value so a selected record filtered
                    // out by the domain still renders among the options
                    // (same approach as StatusBarField's specialData loader).
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
                // Resolve the label from the field's canonical `selection`
                // metadata rather than a subclass `get options()` accessor: the
                // base class must not depend on an option-list getter that not
                // every subclass provides (RadioField exposes `get items()`,
                // not `options`). Filtering applied by subclasses' option lists
                // is irrelevant here — we look up the current value's label.
                return this.props.record.data[this.props.name] !== false
                    ? /** @type {any} */ (
                          this.props.record.fields[this.props.name].selection.find(
                              (o) => o[0] === this.props.record.data[this.props.name],
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

    stringify(value) {
        return JSON.stringify(value);
    }
}
