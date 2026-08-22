/** @odoo-module native */
/**
 * @return {Boolean}
 */
export function areSaleOrderLinesLinked(linkingSaleOrderLine, linkedSaleOrderLine) {
    const linkingId = linkedSaleOrderLine.isNew
        ? linkingSaleOrderLine.data.linked_virtual_id
        : linkingSaleOrderLine.data.linked_line_id.id;
    const linkedId = linkedSaleOrderLine.isNew
        ? linkedSaleOrderLine.data.virtual_id
        : linkedSaleOrderLine.resId;
    return linkingId && linkingId === linkedId;
}

/**
 * @return {Object[]}
 */
export function getLinkedSaleOrderLines(saleOrderLine) {
    const saleOrder = saleOrderLine.model.root;
    return saleOrder.data.line_ids.records.filter((record) =>
        areSaleOrderLinesLinked(record, saleOrderLine),
    );
}

/**
 * @param {ProductComboItem} comboItem
 * @return {Object}
 */
export function serializeComboItem(comboItem) {
    return {
        combo_item_id: comboItem.id,
        product_id: comboItem.product.id,
        no_variant_attribute_value_ids: comboItem.product.selectedNoVariantPtavIds,
        product_custom_attribute_values: comboItem.product.selectedCustomPtavs.map(
            (customPtav) => ({
                custom_product_template_attribute_value_id: customPtav.id,
                custom_value: customPtav.value,
            }),
        ),
    };
}

/**
 * @param {ProductTemplateAttributeLine.props} ptal
 * @return {Object|undefined}
 */
export function getSelectedCustomPtav(ptal) {
    const selectedPtavIds = new Set(ptal.selected_attribute_value_ids);
    return ptal.attribute_values.find(
        (ptav) => ptav.is_custom && selectedPtavIds.has(ptav.id),
    );
}
