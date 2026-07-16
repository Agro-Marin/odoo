/** @odoo-module native */
import { onWillUpdateProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { KeepLast } from "@web/core/utils/concurrency";
import { roundPrecision } from "@web/core/utils/format/numbers";
import {
    Many2ManyTagsFieldColorEditable,
    many2ManyTagsFieldColorEditable,
} from "@web/fields/relational/many2many_tags/many2many_tags_field";
import { Many2XAutocomplete } from "@web/fields/relational/many2x_autocomplete";

// These three helpers are called with `this` bound to the host field component
// (`Many2OneUomField` or `Many2ManyUomTagsField`), which is why they read from
// `this.props` rather than taking an argument: it keeps a single source of truth
// for "which product / quantity is this UoM widget attached to" shared by both
// the many2one and the many2many variants (and their templates).

export function getProductRelatedModel() {
    const field = this.props.record.fields[this.props.productField];
    // The widget is either used alongside a product related field or used in a product view.
    const resModel = field?.relation || this.props.record.resModel;
    if (!["product.product", "product.template"].includes(resModel)) {
        throw new Error(
            `The widget '${this.constructor.name}' (field '${this.props.name}') needs a 'product.product' or 'product.template' field. '${this.props.productField}' is used but is related to '${field?.relation}' model.`,
        );
    }
    return resModel;
}

export function getProductId() {
    const { record } = this.props;
    // On a product form the record *is* the product; elsewhere the product is
    // reached through the configured product field (defaults to `product_id`).
    if (["product.product", "product.template"].includes(record.resModel)) {
        return record.resId || 0;
    }
    return record.data[this.props.productField]?.id || 0;
}

export function getProductQuantity() {
    return this.props.record.data[this.props.quantityField];
}

export class Many2XUomTagsAutocomplete extends Many2XAutocomplete {
    static props = {
        ...Many2XAutocomplete.props,
        productModel: { type: String, optional: true },
        productId: { type: Number, optional: true },
        productQuantity: { type: Number, optional: true },
    };

    setup() {
        super.setup();
        // Serialises the reference-unit fetches: when the product changes faster
        // than the RPCs resolve, only the latest webRead is allowed to write
        // `this.referenceUnit`; superseded ones stay pending forever (KeepLast
        // default), so a slow early response can never clobber a newer one.
        this.referenceUnitLoader = new KeepLast();
        // Fire-and-forget on purpose: an `await` here (or an async
        // onWillUpdateProps callback returning a promise) would put this RPC on
        // OWL's render path and block the field from patching on every product
        // change. `referenceUnit` is only consumed later, in search().
        this.updateReferenceUnit();
        onWillUpdateProps((nextProps) => {
            if (
                nextProps.productModel !== this.props.productModel ||
                nextProps.productId !== this.props.productId
            ) {
                this.updateReferenceUnit(nextProps);
            }
        });
    }

    async updateReferenceUnit(props = this.props) {
        if (!props.productModel || !props.productId) {
            this.referenceUnit = undefined;
            return;
        }
        try {
            const products = await this.referenceUnitLoader.add(
                this.orm.webRead(props.productModel, [props.productId], {
                    specification: {
                        uom_id: {
                            fields: {
                                name: {},
                                factor: {},
                                parent_path: {},
                                rounding: {},
                            },
                        },
                    },
                    context: { active_test: false },
                }),
            );
            this.referenceUnit = products[0]?.uom_id || undefined;
        } catch {
            // deleted or inaccessible product: degrade to a plain autocomplete
            this.referenceUnit = undefined;
        }
    }

    async search(name) {
        const fields = [
            "id",
            "display_name",
            "relative_factor",
            "factor",
            "relative_uom_id",
            "parent_path",
        ];
        const domain = [...this.props.getDomain(), ["name", "ilike", name]];
        const limit = this.props.searchLimit + 1;
        let records;
        if (this.referenceUnit) {
            // Compatible units (sharing the reference unit's root) come first;
            // both queries are bounded, the base component slices the overflow.
            const commonRootDomain = [
                "parent_path",
                "=like",
                `${this.referenceUnit.parent_path.split("/")[0]}/%`,
            ];
            const [common, others] = await Promise.all([
                this.orm.searchRead(
                    this.props.resModel,
                    [...domain, commonRootDomain],
                    fields,
                    { limit },
                ),
                this.orm.searchRead(
                    this.props.resModel,
                    [...domain, "!", commonRootDomain],
                    fields,
                    { limit },
                ),
            ]);
            records = [...common, ...others].slice(0, limit);
        } else {
            records = await this.orm.searchRead(this.props.resModel, domain, fields, {
                limit,
            });
        }
        const reference = this.referenceUnit;
        const referenceRoot = reference?.parent_path.split("/")[0];
        const quantity = this.props.productQuantity || 1;
        return records.map((record) => {
            // Only advertise a conversion for units actually convertible into
            // the product's unit (i.e. sharing its reference root).
            let relativeInfo = "";
            if (
                reference &&
                record.id !== reference.id &&
                record.parent_path.split("/")[0] === referenceRoot
            ) {
                relativeInfo = record.relative_uom_id
                    ? `${roundPrecision(quantity * record.relative_factor, reference.rounding)} ${record.relative_uom_id[1]}`
                    : `${roundPrecision((quantity * record.factor) / reference.factor, reference.rounding)} ${reference.name}`;
            }
            return { ...record, relative_info: relativeInfo };
        });
    }
}

export class Many2ManyUomTagsField extends Many2ManyTagsFieldColorEditable {
    static template = "uom.Many2ManyUomTagsField";
    static components = {
        ...Many2ManyTagsFieldColorEditable.components,
        Many2XAutocomplete: Many2XUomTagsAutocomplete,
    };
    static props = {
        ...Many2ManyTagsFieldColorEditable.props,
        productField: { type: String, optional: true },
        quantityField: { type: String, optional: true },
    };
    static defaultProps = {
        ...Many2ManyTagsFieldColorEditable.defaultProps,
        productField: "product_id",
        quantityField: "product_uom_qty",
    };

    setup() {
        super.setup();
        this.productModel = getProductRelatedModel.call(this);
    }

    get productId() {
        return getProductId.call(this);
    }

    get productQuantity() {
        return getProductQuantity.call(this);
    }
}

export const many2ManyUomTagsField = {
    ...many2ManyTagsFieldColorEditable,
    component: Many2ManyUomTagsField,
    additionalClasses: ["o_field_many2many_tags"],
    supportedOptions: [
        ...(many2ManyTagsFieldColorEditable.supportedOptions || []),
        {
            label: _t("Product Field Name"),
            name: "product_field",
            type: "field",
            availableTypes: ["many2one"],
        },
        {
            label: _t("Quantity Field Name"),
            name: "quantity_field",
            type: "field",
            availableTypes: ["float", "integer"],
        },
    ],
    extractProps({ options }) {
        const props = many2ManyTagsFieldColorEditable.extractProps(...arguments);
        props.productField = options.product_field;
        props.quantityField = options.quantity_field;
        return props;
    },
};

registry.category("fields").add("many2many_uom_tags", many2ManyUomTagsField);
