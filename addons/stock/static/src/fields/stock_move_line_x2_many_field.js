/** @odoo-module native */
import { Domain } from "@web/core/domain";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import {
    useOpenMany2XRecord,
    useSelectCreate,
} from "@web/fields/relational/many2x_autocomplete";
import { X2ManyField, x2ManyField } from "@web/fields/relational/x2many";

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
            onClose: () => {
                this._activeElementOnDialogOpen?.focus();
                this._activeElementOnDialogOpen = null;
            },
        });
    }

    get quantListViewShowOnHandOnly() {
        return true;
    }

    async onAdd({ context } = {}) {
        if (!this.props.record.data.show_quant) {
            return super.onAdd(...arguments);
        }
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

    _unsavedQtyDelta(ml) {
        return ml._values.quantity - ml._changes.quantity;
    }

    async updateDirtyQuantsData() {
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
        record.dirty = true;
    }

    createOpenRecord() {
        this._activeElementOnDialogOpen = document.activeElement;
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
