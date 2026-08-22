/** @odoo-module native */
import {
    ProductLabelSectionAndNoteField,
    productLabelSectionAndNoteField,
} from "@account/components/product_label_section_and_note_field/product_label_section_and_note_field";
import { serializeDateTime } from "@web/core/l10n/dates";
import { rpc } from "@web/core/network";
import { x2ManyCommands } from "@web/core/network";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { uuid } from "@web/core/utils/format/strings";
import { useService } from "@web/core/utils/hooks";
import { sort as sortListRecords } from "@web/model/relational_model";

// `StaticList._sort()` was extracted into this free function; call it directly (as the
// framework's own internal callers do) to re-sort line_ids after a combo mutation.
import { ComboConfiguratorDialog } from "./combo_configurator_dialog/combo_configurator_dialog.js";
import { ProductCombo } from "./models/product_combo.js";
import { ProductConfiguratorDialog } from "./product_configurator_dialog/product_configurator_dialog.js";
import {
    getLinkedSaleOrderLines,
    getSelectedCustomPtav,
    serializeComboItem,
} from "./sale_utils.js";

async function applyProduct(record, product) {
    // handle custom values & no variants
    const customAttributesCommands = [x2ManyCommands.clear()];
    for (const ptal of product.attribute_lines) {
        const selectedCustomPTAV = getSelectedCustomPtav(ptal);
        if (selectedCustomPTAV) {
            customAttributesCommands.push(
                x2ManyCommands.create(undefined, {
                    custom_product_template_attribute_value_id: {
                        id: selectedCustomPTAV.id,
                        display_name: selectedCustomPTAV.name,
                    },
                    custom_value: ptal.customValue,
                }),
            );
        }
    }

    const noVariantPTAVIds = product.attribute_lines
        .filter((ptal) => ptal.create_variant === "no_variant")
        .flatMap((ptal) => ptal.selected_attribute_value_ids);

    // We use `_update` (not locked) instead of `update` (locked) so that multiple records can be
    // updated in parallel (for performance).
    const update_values = {
        product_id: { id: product.id, display_name: product.display_name },
        product_qty: product.quantity,
        product_no_variant_attribute_value_ids: [x2ManyCommands.set(noVariantPTAVIds)],
        product_custom_attribute_value_ids: customAttributesCommands,
    };
    if (product.uom) {
        // only update uom field if uom are enabled (uom_data provided), otherwise we don't have the display_name
        // and the value isn't expected to change anyway.
        update_values.product_uom_id = product.uom;
    }
    await record._update(update_values);
}

export class SaleOrderLineProductField extends ProductLabelSectionAndNoteField {
    static template = "sale.SaleProductField";
    static props = {
        ...super.props,
        readonlyField: { type: Boolean, optional: true },
    };

    setup() {
        super.setup();
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.orm = useService("orm");
    }

    /**
     * Apply a user product selection together with everything it cascades
     * into — the variant lookup, the resulting ``product_id`` write and its
     * onchange — as one unit the model can wait on.
     *
     * The cascade used to hang off a ``useEffect`` on the product id, told
     * apart from an onchange writing the same field by an ``isInternalUpdate``
     * flag. That made its second half a render side effect: between the first
     * onchange resolving and the effect running, the mutex was idle while the
     * line still had no ``product_id``, ``name`` or ``product_uom_id``, and
     * anything asking the model to settle in that window (the
     * ``leaveEditMode`` behind "Add a product", a save, a reload) saw a line
     * with empty required fields and acted on it — "Add a product" silently
     * added nothing. Driving the cascade from the selection removes the flag
     * and the window both.
     *
     * @param {() => Promise<unknown>} applySelection writes the selected value
     * @returns {Promise<void>}
     */
    _selectProduct(applySelection) {
        // Read before the write: the cascade branches on what the line held
        // when the user picked, not on what the selection turned it into.
        const wasCombo = this.isCombo;
        const previousId = this.value && this.value.id;
        return this.props.record.model.trackCompoundUpdate(async () => {
            await applySelection();
            if (!this.value || this.value.id === previousId) {
                return;
            }
            if (wasCombo) {
                // If the previously selected product was a combo, delete its selected combo
                // items before changing the product.
                await this.props.record.update({
                    selected_combo_items: JSON.stringify([]),
                });
            }
            if (this.relation === "product.template" || this.isCombo) {
                await this._onProductTemplateUpdate();
            } else {
                await this._onProductUpdate();
            }
        });
    }

    get productName() {
        if (this.props.name === "product_template_id") {
            const product_id_data = this.props.record.data.product_id;
            if (product_id_data && product_id_data.display_name) {
                return product_id_data.display_name.split("\n")[0];
            }
        }
        return super.productName;
    }
    get isProductClickable() {
        // product form should be accessible if the widget field is readonly
        // or if the line cannot be edited (e.g. locked SO)
        return (
            this.props.readonlyField ||
            (this.props.record.model.root.activeFields.line_ids &&
                this.props.record.model.root._isReadonly("line_ids"))
        );
    }
    get hasConfigurationButton() {
        return this.isConfigurableTemplate || this.isCombo;
    }
    get isConfigurableTemplate() {
        return this.props.record.data.is_configurable_product;
    }
    get isCombo() {
        return (
            this.props.record.data.product_template_id &&
            this.props.record.data.product_type === "combo"
        );
    }
    get isDownpayment() {
        return this.props.record.data.is_downpayment;
    }

    get configurationButtonHelp() {
        return _t("Edit Configuration");
    }

    /**
     * @override
     */
    get sectionAndNoteClasses() {
        return {
            ...super.sectionAndNoteClasses,
            "text-warning":
                !this.isSectionOrSubSection &&
                !this.isNote() &&
                !this.productName &&
                !this.isDownpayment,
        };
    }

    get label() {
        let label = this.props.record.data.name;
        if (
            this.translatedProductName &&
            label.startsWith(this.translatedProductName)
        ) {
            // Remove the translated name as it is already shown to the salesman on the SOL.
            label = label.slice(this.translatedProductName.length + 1); // + "\n"
        } else {
            label = super.label;
        }
        return label;
    }

    get translatedProductName() {
        return this.props.record.data.product_name_translated;
    }

    parseLabel(value) {
        if (!this.translatedProductName) {
            return super.parseLabel(value);
        }
        return (
            (value && this.translatedProductName.concat("\n", value)) ||
            this.translatedProductName
        );
    }

    get m2oProps() {
        const p = super.m2oProps;
        const value = p.value && { ...p.value };
        if (this.isCombo && value && value.display_name) {
            // Show the product quantity next to the product name for combo lines.
            value.display_name = `${value.display_name} x ${this.props.record.data.product_qty}`;
        }
        return {
            ...p,
            canOpen:
                this.props.canOpen && (!this.props.readonly || this.isProductClickable),
            update: (value) => this._selectProduct(() => p.update(value)),
            value,
        };
    }

    get relation() {
        return this.props.record.fields[this.props.name].relation;
    }

    get value() {
        return this.props.record.data[this.props.name];
    }

    async _onProductTemplateUpdate() {
        const result = await this.orm.call(
            "product.template",
            "get_single_product_variant",
            [this.props.record.data.product_template_id.id],
            {
                context: this.context,
            },
        );
        // Every branch below is awaited. `_selectProduct` runs this inside
        // `trackCompoundUpdate`, whose whole purpose is to keep the model from settling
        // mid-cascade; a branch that is merely started escapes that window, and the
        // model reports the line settled while it still holds nothing but `product_id`.
        // That is most visible on the all-preselected combo path, where
        // `_openComboConfigurator` skips the dialog and writes `product_qty`,
        // `selected_combo_items` and `virtual_id` itself before resequencing the list.
        if (result && result.product_id) {
            // `result.product_id` is a scalar id; compare against the m2o's `.id`.
            if (this.props.record.data.product_id?.id !== result.product_id) {
                const productValue = {
                    product_id: {
                        id: result.product_id,
                        display_name: result.product_name,
                    },
                };
                if (result.is_combo) {
                    await this.props.record.update(productValue);
                    await this._openComboConfigurator(
                        false,
                        result.has_optional_products,
                    );
                } else if (result.has_optional_products) {
                    await this._openProductConfigurator();
                } else {
                    await this.props.record.update(productValue);
                    await this._onProductUpdate();
                }
            }
        } else if (!result?.mode || result.mode === "configurator") {
            await this._openProductConfigurator();
        } else {
            // only triggered when sale_product_matrix is installed.
            await this._openGridConfigurator();
        }
    }

    async _openGridConfigurator(edit = false) {} // sale_product_matrix

    async _onProductUpdate() {} // event_booth_sale, event_sale, sale_renting

    onEditConfiguration() {
        if (this.isCombo) {
            this._openComboConfigurator(true);
        } else if (this.isConfigurableTemplate) {
            this._openProductConfigurator(true);
        }
    }

    async _openProductConfigurator(edit = false, selectedComboItems = []) {
        const saleOrderRecord = this.props.record.model.root;
        const saleOrderLine = this.props.record.data;
        const ptavIds = [...this._getVariantPtavIds(saleOrderLine)];
        let customPtavs = [];

        if (edit) {
            /**
             * no_variant and custom attribute don't need to be given to the configurator for new
             * products.
             */
            ptavIds.push(...this._getNoVariantPtavIds(saleOrderLine));
            customPtavs = await this._getCustomPtavs(saleOrderLine);
        }

        this.dialog.add(ProductConfiguratorDialog, {
            productTemplateId: saleOrderLine.product_template_id.id,
            ptavIds: ptavIds,
            customPtavs: customPtavs,
            quantity: saleOrderLine.product_qty,
            productUOMId: saleOrderLine.product_uom_id.id,
            companyId: saleOrderRecord.data.company_id.id,
            pricelistId: saleOrderRecord.data.pricelist_id.id,
            currencyId: saleOrderLine.currency_id.id,
            soDate: serializeDateTime(saleOrderRecord.data.date_order),
            selectedComboItems: selectedComboItems,
            edit: edit,
            save: async (mainProduct, optionalProducts) => {
                // Don't add main product if it's a combo product as it has already been added
                // from combo configurator
                const proms = !selectedComboItems.length
                    ? [applyProduct(this.props.record, mainProduct)]
                    : [];

                // Loop-invariant: every insertion below lands *after* this line, so its
                // own index never moves.
                const comboLineIndex = saleOrderRecord.data.line_ids.records.indexOf(
                    this.props.record,
                );
                for (const [i, product] of optionalProducts.entries()) {
                    const index = comboLineIndex + selectedComboItems.length + i;
                    const line =
                        await saleOrderRecord.data.line_ids.addNewRecordAtIndex(index, {
                            mode: "readonly",
                        });
                    const productData = this._prepareNewLineData(line, product);
                    proms.push(applyProduct(line, productData));
                }

                await Promise.all(proms);
                // Before leaving edit mode, not alongside it: `_onProductUpdate` is where
                // event_sale / sale_renting finish filling the line.
                await this._onProductUpdate();
                saleOrderRecord.data.line_ids.leaveEditMode();
            },
            discard: () => {
                if (!selectedComboItems.length) {
                    // Don't delete the main product if it's a combo product as it has been added
                    // from combo configurator
                    saleOrderRecord.data.line_ids.delete(this.props.record);
                }
            },
            ...this._getAdditionalDialogProps(),
        });
    }

    async _openComboConfigurator(edit = false, hasOptionalProducts = false) {
        const saleOrder = this.props.record.model.root.data;
        const comboLineRecord = this.props.record;
        const comboItemLineRecords = getLinkedSaleOrderLines(comboLineRecord).filter(
            (record) => !!record.data.combo_item_id,
        );
        const selectedComboItems = await Promise.all(
            comboItemLineRecords.map(async (record) => ({
                id: record.data.combo_item_id.id,
                no_variant_ptav_ids: edit ? this._getNoVariantPtavIds(record.data) : [],
                custom_ptavs: edit ? await this._getCustomPtavs(record.data) : [],
            })),
        );
        const { combos, ...remainingData } = await rpc(
            "/sale/combo_configurator/get_data",
            {
                product_tmpl_id: comboLineRecord.data.product_template_id.id,
                currency_id: comboLineRecord.data.currency_id.id,
                quantity: comboLineRecord.data.product_qty,
                date: serializeDateTime(saleOrder.date_order),
                company_id: saleOrder.company_id.id,
                pricelist_id: saleOrder.pricelist_id.id,
                selected_combo_items: selectedComboItems,
                ...this._getAdditionalRpcParams(),
            },
        );

        const comboChoices = combos.map((combo) => new ProductCombo(combo));
        const preselectedComboItems = comboChoices
            .map((combo) => combo.preselectedComboItem)
            .filter(Boolean);
        if (preselectedComboItems.length === comboChoices.length) {
            return this.handleComboSave(
                { quantity: remainingData.quantity },
                preselectedComboItems,
                edit,
                hasOptionalProducts,
            );
        }
        this.dialog.add(ComboConfiguratorDialog, {
            combos: comboChoices,
            ...remainingData,
            company_id: saleOrder.company_id.id,
            pricelist_id: saleOrder.pricelist_id.id,
            date: serializeDateTime(saleOrder.date_order),
            edit: edit,
            // Return the promise (don't fire-and-forget) so the dialog's `confirm`
            // awaits the save: keeps the loading state meaningful and surfaces errors
            // instead of dropping them as unhandled rejections.
            save: (comboProductData, selectedComboItems) =>
                this.handleComboSave(
                    comboProductData,
                    selectedComboItems,
                    edit,
                    hasOptionalProducts,
                ),
            discard: () => saleOrder.line_ids.delete(comboLineRecord),
            ...this._getAdditionalDialogProps(),
        });
    }

    async handleComboSave(
        comboProductData,
        selectedComboItems,
        edit,
        hasOptionalProducts,
    ) {
        const saleOrder = this.props.record.model.root.data;
        const comboLineRecord = this.props.record;
        saleOrder.line_ids.leaveEditMode();
        const comboLineValues = {
            product_qty: comboProductData.quantity,
            selected_combo_items: JSON.stringify(
                selectedComboItems.map(serializeComboItem),
            ),
        };
        if (!edit) {
            comboLineValues.virtual_id = uuid();
        }
        await comboLineRecord.update(comboLineValues);
        // Ensure that the order lines are sorted according to their sequence.
        await sortListRecords(saleOrder.line_ids);

        if (hasOptionalProducts && !edit) {
            const selectedComboProducts = selectedComboItems.map((item) => ({
                name: item.product.display_name,
            }));
            await this._openProductConfigurator(false, selectedComboProducts);
        }
    }

    /**
     * Hook to append additional RPC params in overriding modules.
     *
     * @return {Object} The additional RPC params.
     */
    _getAdditionalRpcParams() {
        return {};
    }

    /**
     * Hook to append additional props in overriding modules.
     *
     * @return {Object} The additional props.
     */
    _getAdditionalDialogProps() {
        return {};
    }

    /**
     * Hook to append extra data in newly created optional product lines.
     */
    _prepareNewLineData(_line, product) {
        return product;
    }

    /**
     * Return the PTAV ids of the provided sale order line.
     *
     * @param saleOrderLine The sale order line
     * @return {Number[]} The sale order line's PTAV ids.
     */
    _getVariantPtavIds(saleOrderLine) {
        return saleOrderLine.product_template_attribute_value_ids.currentIds;
    }

    /**
     * Return the `no_variant` PTAV ids of the provided sale order line.
     *
     * @param saleOrderLine The sale order line
     * @return {Number[]} The sale order line's `no_variant` PTAV ids.
     */
    _getNoVariantPtavIds(saleOrderLine) {
        return saleOrderLine.product_no_variant_attribute_value_ids.currentIds;
    }

    /**
     * Return the custom PTAVs of the provided sale order line.
     *
     * @param saleOrderLine The sale order line
     * @return {Promise<CustomPtav[]>} The sale order line's custom PTAVs.
     */
    async _getCustomPtavs(saleOrderLine) {
        // `product.attribute.custom.value` records are not loaded in the view because sub templates
        // are not loaded in list views. Therefore, we fetch them from the server if the record was
        // saved. Otherwise, we use the value stored on the line.
        const customPtavIds = saleOrderLine.product_custom_attribute_value_ids;
        let customPtavs = [];
        if (customPtavIds.records[0]?.isNew) {
            customPtavs = customPtavIds.records.map((record) => record.data);
        } else if (customPtavIds.currentIds.length) {
            const specification = {
                custom_product_template_attribute_value_id: {
                    fields: { id: {} },
                },
                custom_value: {},
            };
            customPtavs = await this.orm.webRead(
                "product.attribute.custom.value",
                customPtavIds.currentIds,
                { specification },
            );
        }
        return customPtavs.map((customPtav) => ({
            id:
                customPtav.custom_product_template_attribute_value_id &&
                customPtav.custom_product_template_attribute_value_id.id,
            value: customPtav.custom_value,
        }));
    }
}

export const saleOrderLineProductField = {
    ...productLabelSectionAndNoteField,
    component: SaleOrderLineProductField,
    extractProps(fieldInfo, dynamicInfo) {
        return {
            ...productLabelSectionAndNoteField.extractProps(fieldInfo, dynamicInfo),
            readonlyField: dynamicInfo.readonly,
        };
    },
    // What *this* component reads. `service_tracking` used to be declared here and is
    // read only by event_sale and event_booth_sale, which now each declare it: a
    // duplicate is harmless because `addFieldDependencies` merges by field name.
    fieldDependencies: [
        { name: "is_configurable_product", type: "boolean" },
        { name: "product_type", type: "selection" },
        { name: "product_template_attribute_value_ids", type: "many2many" },
        { name: "product_name_translated", type: "char" },
    ],
};

registry.category("fields").add("sol_product_many2one", saleOrderLineProductField);
