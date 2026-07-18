/** @odoo-module native */
import { Domain } from "@web/core/domain";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import {
    useOpenMany2XRecord,
    useSelectCreate,
} from "@web/fields/relational/many2x_autocomplete";
import { X2ManyField, x2ManyField } from "@web/fields/relational/x2many/x2many_field";

export class SMLX2ManyField extends X2ManyField {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.dirtyQuantsData = new Map();
        const selectCreate = useSelectCreate({
            resModel: "stock.quant",
            activeActions: this.activeActions,
            onSelected: (resIds) => this.selectRecord(resIds),
            onCreateEdit: () => this.createOpenRecord(),
        });

        this.selectCreate = selectCreate;
        this.openQuantRecord = useOpenMany2XRecord({
            resModel: "stock.quant",
            activeActions: this.activeActions,
            onRecordSaved: (record) => this.selectRecord([record.resId]),
            fieldString: this.props.string,
            is2Many: true,
            // `onClose` is a hook-config option (not a per-call one): restore
            // the focus captured by createOpenRecord() when the dialog closes.
            onClose: () => {
                this._activeElementOnDialogOpen?.focus();
                this._activeElementOnDialogOpen = null;
            },
        });
    }

    get quantListViewShowOnHandOnly() {
        return true; // To override in mrp_subcontracting
    }

    async onAdd({ context } = {}) {
        if (!this.props.record.data.show_quant) {
            return super.onAdd(...arguments);
        }
        // Compute the quant offset from move lines quantity changes that were not saved yet.
        // Hence, did not yet affect quant's quantity in DB.
        await this.updateDirtyQuantsData();
        context = {
            ...context,
            single_product: true,
            list_view_ref: "stock.view_stock_quant_list_simple",
        };
        const productName = this.props.record.data.product_id.display_name;
        const title = _t("Add line: %s", productName);
        let domain = [
            ["product_id", "=", this.props.record.data.product_id.id],
            ["location_id", "child_of", this.props.context.default_location_id],
            ["quantity", ">", 0.0],
        ];
        if (this.quantListViewShowOnHandOnly) {
            domain.push(["on_hand", "=", true]);
        }
        if (this.dirtyQuantsData.size) {
            const notFullyUsed = [];
            const fullyUsed = [];
            for (const [quantId, quantData] of this.dirtyQuantsData.entries()) {
                if (quantData.available_quantity > 0) {
                    notFullyUsed.push(quantId);
                } else {
                    fullyUsed.push(quantId);
                }
            }
            if (fullyUsed.length) {
                domain = Domain.and([domain, [["id", "not in", fullyUsed]]]).toList();
            }
            if (notFullyUsed.length) {
                domain = Domain.or([domain, [["id", "in", notFullyUsed]]]).toList();
            }
        }
        return this.selectCreate({ domain, context, title });
    }

    /**
     * Pending, not-yet-saved change to a move line's quantity, as
     * `savedQty - currentQty` (negative when the line now reserves more than the
     * DB reflects). Reads the relational Record's private `_values`/`_changes`
     * because the last-saved baseline is not exposed publicly (`data.quantity` is
     * the current, edited value) and the quant's DB `available_quantity` does not
     * yet account for unsaved line-quantity edits. Returns a falsy `NaN` when the
     * quantity is unchanged, so it also serves as a "quantity is dirty" test.
     * Isolated here so this fragile coupling lives in one place.
     */
    _unsavedQtyDelta(ml) {
        return ml._values.quantity - ml._changes.quantity;
    }

    async updateDirtyQuantsData() {
        // Since changes of move line quantities will not affect the available quantity of the quant before
        // the record has been saved, it is necessary to determine the offset of the DB quant data.
        this.dirtyQuantsData.clear();
        const dirtyQuantityMoveLines = this._move_line_ids.filter(
            (ml) => !ml.data.quant_id && this._unsavedQtyDelta(ml),
        );
        const dirtyQuantMoveLines = this._move_line_ids.filter(
            (ml) => ml.data.quant_id.id,
        );
        const dirtyMoveLines = [...dirtyQuantityMoveLines, ...dirtyQuantMoveLines];
        if (!dirtyMoveLines.length) {
            return;
        }
        const match = await this.orm.call(
            "stock.move.line",
            "get_move_line_quant_match",
            [
                this._move_line_ids.filter((rec) => rec.resId).map((rec) => rec.resId),
                this.props.record.resId,
                dirtyMoveLines.filter((rec) => rec.resId).map((rec) => rec.resId),
                dirtyQuantMoveLines.map((ml) => ml.data.quant_id.id),
            ],
            {},
        );
        const quants = match[0];
        if (!quants.length) {
            return;
        }
        const dbMoveLinesData = new Map();
        for (const data of match[1]) {
            dbMoveLinesData.set(data[0], {
                quantity: data[1].quantity,
                quantId: data[1].quant_id,
            });
        }
        const offsetByQuant = new Map();
        for (const ml of dirtyQuantMoveLines) {
            const quantId = ml.data.quant_id.id;
            offsetByQuant.set(
                quantId,
                (offsetByQuant.get(quantId) || 0) - ml.data.quantity,
            );
            const dbQuantId = dbMoveLinesData.get(ml.resId)?.quantId;
            if (dbQuantId && quantId !== dbQuantId) {
                offsetByQuant.set(
                    dbQuantId,
                    (offsetByQuant.get(dbQuantId) || 0) +
                        dbMoveLinesData.get(ml.resId).quantity,
                );
            }
        }
        const offsetByQuantity = new Map();
        for (const ml of dirtyQuantityMoveLines) {
            offsetByQuantity.set(ml.resId, this._unsavedQtyDelta(ml));
        }
        for (const quant of quants) {
            const quantityOffset = quant[1].move_line_ids
                .map((ml) => offsetByQuantity.get(ml) || 0)
                .reduce((val, sum) => val + sum, 0);
            const quantOffset = offsetByQuant.get(quant[0]) || 0;
            this.dirtyQuantsData.set(quant[0], {
                available_quantity:
                    quant[1].available_quantity + quantityOffset + quantOffset,
            });
        }
    }

    async selectRecord(res_ids) {
        const demand =
            this.props.record.data.product_uom_qty -
            this._move_line_ids
                .map((ml) => ml.data.quantity)
                .reduce((val, sum) => val + sum, 0);
        const params = {
            context: { default_quant_id: res_ids[0] },
        };
        if (demand <= 0) {
            params.context.default_quantity = 0;
        } else if (this.dirtyQuantsData.has(res_ids[0])) {
            params.context.default_quantity = Math.min(
                this.dirtyQuantsData.get(res_ids[0]).available_quantity,
                demand,
            );
        }
        const record = await this.list.addNewRecord(params);
        // Make it dirty to force the save of the record. addNewRecord make
        // the new record dirty === False by default to remove them at unfocus event
        record.dirty = true;
    }

    createOpenRecord() {
        this._activeElementOnDialogOpen = document.activeElement;
        // `immediate` is the second positional argument of the open function
        // returned by useOpenMany2XRecord (passing it inside the first object,
        // as before, silently ignored it).
        this.openQuantRecord(
            {
                context: {
                    ...this.props.context,
                    form_view_ref: "stock.view_stock_quant_form",
                },
            },
            true,
        );
    }

    get _move_line_ids() {
        return this.props.record.data.move_line_ids.records;
    }
}

export const smlX2ManyField = {
    ...x2ManyField,
    component: SMLX2ManyField,
};

registry.category("fields").add("sml_x2_many", smlX2ManyField);
