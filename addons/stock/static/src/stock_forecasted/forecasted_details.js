/** @odoo-module native */
import { Component, onWillUpdateProps } from "@odoo/owl";
import { useOperationGuard } from "@stock/utils/use_operation_guard";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { formatFloat } from "@web/fields/formatters";

export class ForecastedDetails extends Component {
    static template = "stock.ForecastedDetails";
    static props = { docs: Object, openView: Function, reloadReport: Function };

    setup() {
        this.orm = useService("orm");
        // Shared busy flag: while a reserve/unreserve/priority RPC (and the
        // reloadReport it triggers) is in flight, all three handlers are inert
        // and the template disables the controls.
        this.opGuard = useOperationGuard();
        this._reserve = this.opGuard.guard(this._reserve.bind(this));
        this._unreserve = this.opGuard.guard(this._unreserve.bind(this));
        this._onClickChangePriority = this.opGuard.guard(
            this._onClickChangePriority.bind(this),
        );
        this._deriveLinesData(this.props.docs);
        onWillUpdateProps((nextProps) => this._deriveLinesData(nextProps.docs));

        this._formatFloat = (num) =>
            formatFloat(num, { digits: [false, this.props.docs.precision] });
    }

    /**
     * Derives everything the template reads (local line list, groupings,
     * totals, merge data) from `docs`. Called from setup and again on every
     * props update. The line list is a local copy: sorting/splicing during the
     * derivation must never write back into the parent-owned `props.docs`.
     */
    _deriveLinesData(docs) {
        this.docs = docs;
        this._prepareLines();
        this._groupLines();
        this._prepareData();
        this._mergeLines();
    }

    async _reserve(move_id) {
        await this.orm.call(
            "stock.forecasted_product_product",
            "action_reserve_linked_picks",
            [move_id],
        );
        this.props.reloadReport();
    }

    async _unreserve(move_id) {
        await this.orm.call(
            "stock.forecasted_product_product",
            "action_unreserve_linked_picks",
            [move_id],
        );
        this.props.reloadReport();
    }

    async _onClickChangePriority(modelName, record) {
        const value = record.priority === "0" ? "1" : "0";

        await this.orm.call(modelName, "write", [[record.id], { priority: value }]);
        this.props.reloadReport();
    }

    _onHandCondition(line) {
        return (
            !line.document_in &&
            !line.in_transit &&
            line.replenishment_filled &&
            line.document_out
        );
    }

    _reconciledCondition(line) {
        return (
            line.document_in &&
            !line.in_transit &&
            line.replenishment_filled &&
            line.document_out
        );
    }

    _freeStockCondition(line) {
        return (
            !line.document_in &&
            !line.in_transit &&
            line.replenishment_filled &&
            !line.document_out
        );
    }

    _notAvailableCondition(line) {
        return (
            !line.document_in &&
            !line.in_transit &&
            !line.replenishment_filled &&
            line.document_out
        );
    }

    //Extend this to add new lines grouping
    _groupLines() {
        this._groupLinesByProduct();
        this._groupOnHandLinesByProduct();
        this._groupReconciledLinesByProduct();
        this._groupFreeStockLinesByProduct();
        this._groupNotAvailableLinesByProduct();
    }

    _groupLinesByProduct() {
        this.LinesPerProduct = {};
        for (const line of this.lines) {
            const key = line.product.id;
            (this.LinesPerProduct[key] ??= []).push(line);
        }
    }

    _groupOnHandLinesByProduct() {
        this.OnHandLinesPerProduct = {};
        for (const line of this.lines) {
            if (this._onHandCondition(line)) {
                const key = line.product.id;
                (this.OnHandLinesPerProduct[key] ??= []).push(line);
            }
        }
    }

    _groupReconciledLinesByProduct() {
        this.ReconciledLinesPerProduct = {};
        for (const line of this.lines) {
            if (this._reconciledCondition(line)) {
                const key = line.product.id;
                (this.ReconciledLinesPerProduct[key] ??= []).push(line);
            }
        }
    }

    _groupNotAvailableLinesByProduct() {
        this.NotAvailableLinesPerProduct = {};
        for (const line of this.lines) {
            if (this._notAvailableCondition(line)) {
                const key = line.product.id;
                (this.NotAvailableLinesPerProduct[key] ??= []).push(line);
            }
        }
    }

    _groupFreeStockLinesByProduct() {
        // NB: no `removal_date` filtering here — that key only exists when
        // product_expiry is installed, and product_expiry's override of
        // `_freeStockCondition` applies it.
        this.FreeStockLinesPerProduct = {};
        for (const line of this.lines) {
            if (this._freeStockCondition(line)) {
                const key = line.product.id;
                (this.FreeStockLinesPerProduct[key] ??= []).push(line);
            }
        }
    }

    _prepareLines() {
        // Copy first (extensions sort `docs.lines` in place before calling
        // super, so the copy must be taken here, not earlier): every later
        // step — grouping, splicing, merging — works on this local array only.
        this._lines = [...this.docs.lines];
        if (this.multipleProducts) {
            this._lines.sort((a, b) => (a.product.id || 0) - (b.product.id || 0));
        }
    }

    _prepareData() {
        this.OnHandTotalQty = Object.fromEntries(
            Object.entries(this.OnHandLinesPerProduct).map(([id, lines]) => [
                id,
                lines.reduce((sum, line) => sum + line.quantity, 0),
            ]),
        );
        this.AvailableOnHandTotalQty = Object.fromEntries(
            Object.entries(this.OnHandLinesPerProduct).map(([id, lines]) => [
                id,
                lines.reduce(
                    (sum, line) => sum + (line.reservation ? 0 : line.quantity),
                    0,
                ),
            ]),
        );
        for (const productId of this.productIds) {
            if (
                !(productId in this.FreeStockLinesPerProduct) ||
                !(productId in this.LinesPerProduct)
            ) {
                continue;
            }
            const lines = this.FreeStockLinesPerProduct[productId];
            if (
                this.LinesPerProduct[productId].length > 1 &&
                lines.length === 1 &&
                lines[0]?.quantity === 0
            ) {
                const removeIndex = this.lines.indexOf(lines[0]);
                this.lines.splice(removeIndex, 1);
            }
        }
    }

    _mergeLines() {
        const lines = this.lines;
        this.mergesLinesData = {};
        let lastIndex = 0;
        for (let i = 0; i < lines.length - 1; i++) {
            const line = lines[i];
            const nextLine = lines[i + 1];
            if (
                line.product.id !== nextLine.product.id ||
                !this._sameLineRule(line, nextLine)
            ) {
                lastIndex = i + 1;
                continue;
            }
            if (!this.mergesLinesData[lastIndex]) {
                this.mergesLinesData[lastIndex] = {
                    rowcount: 1,
                    tot_qty: line.quantity,
                };
            }
            this.mergesLinesData[lastIndex].rowcount += 1;
            this.mergesLinesData[lastIndex].tot_qty += nextLine.quantity;
        }
    }

    _sameLineRule(line, nextLine) {
        const OnHand = this.OnHandLinesPerProduct[line.product.id] || [];
        const NotAvailable = this.NotAvailableLinesPerProduct[line.product.id] || [];
        const sameReceiptDate = line.receipt_date === nextLine.receipt_date;
        return (
            (this.sameDocumentIn(line, nextLine) && sameReceiptDate) ||
            (OnHand.includes(line) && OnHand.includes(nextLine)) ||
            (NotAvailable.includes(line) && NotAvailable.includes(nextLine))
        );
    }

    /**
     * Whether the Reserve/Unreserve action is shown for `line`, the datapoint at
     * `lineIndex` in `this.lines`. The index is passed explicitly by the template
     * — do not rely on t-foreach scope variables leaking into `this`.
     */
    displayReserve(line, lineIndex) {
        let splittedLine = true;
        if (lineIndex - 1 >= 0) {
            const previousLine = this.lines[lineIndex - 1];
            const sameProduct = line.product.id === previousLine.product.id;
            const isOnHandSplittedLine =
                this.OnHandLinesPerProduct[line.product.id] &&
                this.OnHandLinesPerProduct[line.product.id].some((l) =>
                    this.sameDocumentOut(l, line),
                );
            const isReconciledSplittedLine =
                this.ReconciledLinesPerProduct[line.product.id] &&
                !this.isReconciled(line) &&
                this.ReconciledLinesPerProduct[line.product.id].some((l) =>
                    this.sameDocumentOut(l, line),
                );
            splittedLine =
                sameProduct &&
                (this.sameDocumentOut(line, previousLine) ||
                    isOnHandSplittedLine ||
                    isReconciledSplittedLine);
        }
        const hasFreeStock = this.props.docs.product[line.product.id].qty_free > 0;
        return (
            this.props.docs.user_can_edit_pickings &&
            !line.in_transit &&
            this.canReserveOperation(line) &&
            (this.isOnHand(line) || (hasFreeStock && !splittedLine))
        );
    }

    canReserveOperation(line) {
        return line.move_out?.picking_id;
    }

    futureVirtualAvailable(line) {
        const product = this.props.docs.product[line.product.id];
        return product.qty_available_virtual + product.qty.in - product.qty.out;
    }

    sameDocumentIn(line1, line2) {
        return this._sameDocument(line1, line2, "document_in");
    }

    sameDocumentOut(line1, line2) {
        return this._sameDocument(line1, line2, "document_out");
    }

    _sameDocument(line1, line2, docField) {
        return (
            line1[docField] &&
            line2[docField] &&
            line1[docField].id === line2[docField].id &&
            line1[docField]._name === line2[docField]._name &&
            line1[docField].name === line2[docField].name
        );
    }

    isOnHand(line) {
        return Boolean(this.OnHandLinesPerProduct[line.product.id]?.includes(line));
    }

    isReconciled(line) {
        return Boolean(this.ReconciledLinesPerProduct[line.product.id]?.includes(line));
    }

    get freeStockLabel() {
        return _t("Free Stock");
    }

    /**
     * Full translatable sentence for an incoming document's expected receipt —
     * built in one piece so translators see the whole phrase, not fragments.
     */
    incomingSentence(line, quantity) {
        return _t("%(quantity)s %(uom)s expected on %(date)s", {
            quantity: this._formatFloat(quantity),
            uom: line.uom_id.display_name,
            date: line.receipt_date,
        });
    }

    stockToReserveSentence(line) {
        return _t("Stock To Reserve: %(quantity)s %(uom)s", {
            quantity: this._formatFloat(this.OnHandTotalQty[line.product.id]),
            uom: line.uom_id.display_name,
        });
    }

    /**
     * Local, derived copy of `docs.lines` (see _deriveLinesData) — never the
     * parent-owned array itself.
     */
    get lines() {
        return this._lines;
    }

    get multipleProducts() {
        return this.docs.multiple_product;
    }

    get productIds() {
        return Object.keys(this.docs.product).map(Number);
    }
}
