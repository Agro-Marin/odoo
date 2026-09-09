/** @odoo-module native */
import { getSectionRecords } from "@account/components/section_and_note_fields_backend/section_and_note_fields_backend";
import {
    getRecordsToRecompute,
    handleQuantityAdjustment,
} from "@sale_management/fields/section_optional_line_utils";
import { SaleOrderLineListRenderer } from "@sale/js/sale_order_line_field/sale_order_line_field";
import { makeContext } from "@web/core/context";
import { x2ManyCommands } from "@web/core/network";
import { patch } from "@web/core/utils/patch";
import { listId } from "@web/model/relational_model";

patch(SaleOrderLineListRenderer.prototype, {
    setup() {
        super.setup();
        this.copyFields.push("is_optional");
    },

    /** @see handleQuantityAdjustment in section_optional_line_utils.js — */
    get optionalQuantityField() {
        return "product_qty";
    },

    disableCompositionButton(record) {
        return (
            super.disableCompositionButton(record) ||
            this.shouldCollapse(record, "is_optional", true)
        );
    },

    disablePricesButton(record) {
        return (
            super.disablePricesButton(record) ||
            this.shouldCollapse(record, "is_optional", true)
        );
    },

    disableOptionalButton(record) {
        return (
            this.shouldCollapse(record, "is_optional") ||
            this.shouldCollapse(record, "collapse_prices", true) ||
            this.shouldCollapse(record, "collapse_composition", true)
        );
    },

    /** @override */
    buildRowApi() {
        return {
            ...super.buildRowApi(),
            disableOptionalButton: (record) => this.disableOptionalButton(record),
            toggleIsOptional: (record) =>
                this.toggleIsOptional(this.resolveRowRecord(record)),
        };
    },

    /** @override */
    getRowProps(record, group, groupId) {
        return {
            ...super.getRowProps(record, group, groupId),
            mutedOptional: this.shouldCollapse(record, "is_optional", true),
        };
    },

    get isCurrentSectionOptional() {
        if (this.props.list.records.length === 0) return false;

        return this.shouldCollapse(
            this.props.list.records[this.props.list.records.length - 1],
            "is_optional",
            true,
        );
    },

    add(params) {
        params.context = this.getCreateContext(params);
        super.add(params);
    },

    getCreateContext(params) {
        const evaluatedContext = makeContext([params.context]);
        if (
            !evaluatedContext[`default_display_type`] &&
            this.isCurrentSectionOptional
        ) {
            return {
                ...evaluatedContext,
                [`default_${this.optionalQuantityField}`]: 0,
            };
        }
        return params.context;
    },

    getInsertLineContext(record, addSubSection) {
        if (this.shouldCollapse(record, "is_optional", true) && !addSubSection) {
            return {
                ...super.getInsertLineContext(record, addSubSection),
                [`default_${this.optionalQuantityField}`]: 0,
            };
        }
        return super.getInsertLineContext(record, addSubSection);
    },

    getRowClass(record) {
        let rowClasses = super.getRowClass(record);
        if (this.shouldCollapse(record, "is_optional", true)) {
            rowClasses += " text-primary";
        }
        return rowClasses;
    },

    /** @override */
    async toggleCollapse(record, fieldName) {
        await super.toggleCollapse(record, fieldName);

        if (this.isTopSection(record) && record.data[fieldName]) {
            const commands = [];

            for (const sectionRecord of getSectionRecords(this.props.list, record)) {
                if (this.isSubSection(sectionRecord)) {
                    commands.push(
                        x2ManyCommands.update(listId(sectionRecord), {
                            is_optional: false,
                        }),
                    );
                }
            }

            if (commands.length) {
                await this.props.list.applyCommands(commands, { sort: true });
            }
        }
    },

    async toggleIsOptional(record) {
        const setOptional = !record.data.is_optional;
        const qtyField = this.optionalQuantityField;

        const commands = [
            x2ManyCommands.update(listId(record), {
                is_optional: setOptional,
            }),
        ];

        const proms = [];
        for (const sectionRecord of getSectionRecords(this.props.list, record)) {
            let changes = {};

            if (!sectionRecord.data.display_type) {
                if (setOptional) {
                    changes = { [qtyField]: 0, price_total: 0, price_subtotal: 0 };
                } else {
                    proms.push(
                        sectionRecord.update({
                            [qtyField]: sectionRecord.data[qtyField] || 1,
                        }),
                    );
                }
            } else if (this.isSubSection(sectionRecord)) {
                changes = setOptional && {
                    collapse_composition: false,
                    collapse_prices: false,
                };
            }

            if (Object.keys(changes).length) {
                commands.push(x2ManyCommands.update(listId(sectionRecord), changes));
            }
        }

        await this.props.list.applyCommands(commands, { sort: true });
        await Promise.all(proms);
    },

    /** @override */
    async sortDrop(dataRowId, dataGroupId, { element, previous }) {
        const record = this.props.list.records.find((r) => r.id === dataRowId);
        const recordMap = this._getRecordsToRecompute(
            record,
            previous ? previous.dataset.id : null,
        );

        await super.sortDrop(dataRowId, dataGroupId, { element, previous });

        await this._handleQuantityAdjustment(recordMap);
    },

    /** @see getRecordsToRecompute in section_optional_line_utils.js — shared */
    _getRecordsToRecompute(record, targetId) {
        return getRecordsToRecompute(this, record, targetId);
    },

    /** @see handleQuantityAdjustment in section_optional_line_utils.js — */
    async _handleQuantityAdjustment(recordMap) {
        return handleQuantityAdjustment(this, recordMap);
    },

    /** @override */
    resetOnResequence(record, parentSection) {
        return (
            super.resetOnResequence(record, parentSection) ||
            (this.isSubSection(record) &&
                parentSection?.data.is_optional &&
                (record.data.collapse_composition ||
                    record.data.collapse_prices ||
                    record.data.is_optional))
        );
    },

    fieldsToReset() {
        return { ...super.fieldsToReset(), is_optional: false };
    },

    async moveCombo(record, direction) {
        const wasOptional = this.shouldCollapse(record, "is_optional");

        await super.moveCombo(record, direction);

        const isOptional = this.shouldCollapse(record, "is_optional");
        const qtyField = this.optionalQuantityField;

        if (wasOptional && !isOptional && !record.data[qtyField]) {
            await record.update({ [qtyField]: 1 });
        } else if (!wasOptional && isOptional) {
            await record.update({ [qtyField]: 0 });
        }
    },
});
