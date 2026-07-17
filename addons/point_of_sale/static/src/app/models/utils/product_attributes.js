/** @odoo-module native */

// Product-template-attribute exclusion logic extracted from PosStore. Pure
// functions of the store; PosStore keeps thin delegating methods so patchers and
// the product configurator (which reads `pos.doHaveConflictWith`) are unaffected.
// The exclusion map itself stays on the store as `pos.productAttributesExclusion`.

export function computeProductAttributesExclusion(pos, excl = false) {
    // A full recompute (no incremental `excl` payload) starts fresh:
    // accumulating onto the existing map kept exclusions deleted in the
    // backend blocking valid combinations until reload.
    const exclusions = excl ? pos.productAttributesExclusion || new Map() : new Map();

    const addExclusion = (key, value) => {
        if (!exclusions.has(key)) {
            exclusions.set(key, new Set());
        }
        exclusions.get(key).add(value);
    };

    for (const exclusion of excl ||
        pos.models["product.template.attribute.exclusion"].getAll()) {
        const ptavId = exclusion.product_template_attribute_value_id.id;
        for (const { id: valueId } of exclusion.value_ids) {
            addExclusion(ptavId, valueId);
            addExclusion(valueId, ptavId);
        }
    }
    return exclusions;
}

export function doHaveConflictWith(pos, value, selectedValues) {
    const exclusions = pos.productAttributesExclusion.get(value.id);
    if (!exclusions) {
        return false;
    }
    const selectedValueIds = new Set(selectedValues.map((v) => v.id));
    for (const exclusionId of exclusions) {
        if (selectedValueIds.has(exclusionId)) {
            return true;
        }
    }
    return false;
}
