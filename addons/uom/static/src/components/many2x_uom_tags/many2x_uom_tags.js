/** @odoo-module native */
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { Many2XAutocomplete } from "@web/fields/relational/many2x_autocomplete";
import {
    Many2ManyTagsFieldColorEditable,
    many2ManyTagsFieldColorEditable,
} from "@web/fields/relational/many2many_tags/many2many_tags_field";
import { roundPrecision } from "@web/core/utils/format/numbers";
import { onWillUpdateProps } from "@odoo/owl";

export function getProductRelatedModel() {
    const field = this.props.record.fields[this.props.productField];
    // The widget is either used alongisde a product related field or either used in a product view.
    let resModel = field?.relation || this.props.record.resModel;
    if (!["product.product", "product.template"].includes(resModel)) {
        throw new Error(`The widget '${this.constructor.name}' (field '${this.props.name}') needs a 'product.product' or 'product.template' field. '${this.props.productField}' is used but is related to '${field?.relation}' model.`);
    }
    return resModel;
}

export class Many2XUomTagsAutocomplete extends Many2XAutocomplete {
    static props = {
        ...Many2XAutocomplete.props,
        productModel: { type: String, optional: true },
        productId: { type: Number, optional: true },
        productQuantity: { type: Number, optional: true },
    };

    async setup() {
        super.setup();
        onWillUpdateProps(async (nextProps) => {
            if (nextProps.productModel !== this.props.productModel ||
                nextProps.productId !== this.props.productId
            ) {
                await this.updateReferenceUnit(nextProps);
            }
        });
        await this.updateReferenceUnit();
    }

    async updateReferenceUnit(props = this.props) {
        if (!props.productModel || !props.productId) {
            this.referenceUnit = undefined;
            return;
        }
        try {
            const products = await this.orm.webRead(props.productModel, [props.productId], {
                specification: {
                    uom_id: { fields: { name: {}, factor: {}, parent_path: {}, rounding: {} } },
                },
                context: { active_test: false },
            });
            this.referenceUnit = products[0]?.uom_id || undefined;
        } catch {
            // deleted or inaccessible product: degrade to a plain autocomplete
            this.referenceUnit = undefined;
        }
    }

    async search(name) {
        const fields = ["id", "display_name", "relative_factor", "factor", "relative_uom_id", "parent_path"];
        const domain = [...this.props.getDomain(), ["name", "ilike", name]];
        const limit = this.props.searchLimit + 1;
        let records;
        if (this.referenceUnit) {
            // Compatible units (sharing the reference unit's root) come first;
            // both queries are bounded, the base component slices the overflow.
            const commonRootDomain = ["parent_path", "=like", `${this.referenceUnit.parent_path.split("/")[0]}/%`];
            const [common, others] = await Promise.all([
                this.orm.searchRead(this.props.resModel, [...domain, commonRootDomain], fields, { limit }),
                this.orm.searchRead(this.props.resModel, [...domain, "!", commonRootDomain], fields, { limit }),
            ]);
            records = [...common, ...others].slice(0, limit);
        } else {
            records = await this.orm.searchRead(this.props.resModel, domain, fields, { limit });
        }
        const hasCommonReference = (uom) =>
            uom.parent_path.split("/")[0] === this.referenceUnit.parent_path.split("/")[0];
        return records.map((record) => {
            // Only advertise a conversion for units actually convertible into
            // the product's unit.
            let relativeInfo = "";
            if (this.referenceUnit && record.id !== this.referenceUnit.id && hasCommonReference(record)) {
                relativeInfo = record.relative_uom_id
                    ? `${roundPrecision((this.props.productQuantity || 1) * record.relative_factor, this.referenceUnit.rounding)} ${record.relative_uom_id[1]}`
                    : `${roundPrecision((this.props.productQuantity || 1) * record.factor / this.referenceUnit.factor, this.referenceUnit.rounding)} ${this.referenceUnit.name}`;
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
    }
    static defaultProps = {
        ...Many2ManyTagsFieldColorEditable.defaultProps,
        productField: "product_id",
        quantityField: "product_uom_qty",
    }

    async setup() {
        super.setup();
        this.productModel = getProductRelatedModel.call(this);
    }
}

export const many2ManyUomTagsField = {
    ...many2ManyTagsFieldColorEditable,
    component: Many2ManyUomTagsField,
    additionalClasses: ['o_field_many2many_tags'],
    supportedOptions: [
        ...(many2ManyTagsFieldColorEditable.supportedOptions || []),
        {
            label: _t("Product Field Name"),
            name: "product_field",
            type: "field",
            availableTypes: ["many2one"]
        },
        {
            label: _t("Quantity Field Name"),
            name: "quantity_field",
            type: "field",
            availableTypes: ["float", "integer"]
        }
    ],
    extractProps({ options }) {
        const props = many2ManyTagsFieldColorEditable.extractProps(...arguments);
        props.productField = options.product_field;
        props.quantityField = options.quantity_field;
        return props;
    },
};

registry.category("fields").add("many2many_uom_tags", many2ManyUomTagsField);
