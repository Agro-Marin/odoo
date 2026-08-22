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

    /**
     * The form's current view of this move's lines, as the server expects it.
     *
     * `quant_id` is `store=False`, so a value here is always a quant the user
     * just picked rather than anything the database knows about.
     */
    get _pendingLines() {
        return this._move_line_ids.map((ml) => ({
            id: ml.resId || false,
            quantity: ml.data.quantity,
            quant_id: ml.data.quant_id?.id || false,
        }));
    }

    /**
     * True once the form holds something the database does not: an edited line,
     * a deleted one, or a quant picked by hand. Nothing to reconcile otherwise,
     * so the round trip is skipped.
     */
    get _hasPendingChanges() {
        // The move record covers a deleted line, which leaves nothing behind to
        // ask; the per-line checks cover edits and picks on a move that is
        // otherwise clean. Erring towards the round trip is cheap, a stale
        // availability is not.
        return (
            this.props.record.dirty ||
            this._move_line_ids.some(
                (ml) => ml.dirty || !ml.resId || ml.data.quant_id?.id,
            )
        );
    }

    /**
     * Ask the server how much of each candidate quant is still free, given what
     * the form is holding. The arithmetic and the unit conversion both live in
     * `get_pending_quant_availability`: quant availability is in the product's
     * reference UoM and form quantities are in the line's, and only the server
     * has the factor. The numbers that come back are in the move's UoM, which is
     * what `onAdd` and `selectRecord` below work in.
     */
    async updateDirtyQuantsData() {
        this.dirtyQuantsData.clear();
        if (!this._hasPendingChanges) {
            return;
        }
        const availability = await this.orm.call(
            "stock.move.line",
            "get_pending_quant_availability",
            [this.props.record.resId, this._pendingLines],
        );
        for (const [quantId, availableQuantity] of availability) {
            this.dirtyQuantsData.set(quantId, {
                available_quantity: availableQuantity,
            });
        }
    }

    async selectRecord(res_ids) {
        const demand =
            this.props.record.data.product_uom_qty -
            this._move_line_ids
                .map((ml) => ml.data.quantity)
                .reduce((sum, quantity) => sum + quantity, 0);
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
