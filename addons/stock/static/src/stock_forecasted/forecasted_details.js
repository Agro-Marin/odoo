/** @odoo-module native */
import { Component, onWillUpdateProps, useState } from "@odoo/owl";
import { useOperationGuard } from "@stock/utils/use_operation_guard";
import { formatFieldFloat } from "@web/core/formatters";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";

/**
 * @param {object} line
 * @returns {"inTransit"|"onHand"|"reconciled"|"freeStock"|"notAvailable"|"incoming"|null}
 */
export function classifyLine(line) {
    if (line.in_transit) {
        return "inTransit";
    }
    const hasIn = Boolean(line.document_in);
    const hasOut = Boolean(line.document_out);
    const isFilled = Boolean(line.replenishment_filled);
    if (isFilled && hasOut) {
        return hasIn ? "reconciled" : "onHand";
    }
    if (isFilled && !hasOut) {
        return hasIn ? "incoming" : "freeStock";
    }
    if (!isFilled && hasOut && !hasIn) {
        return "notAvailable";
    }
    return null;
}

function documentKey(document) {
    return document ? `${document._name}|${document.id}|${document.name}` : null;
}

export class ForecastedDetails extends Component {
    static template = "stock.ForecastedDetails";
    static props = { docs: Object, openView: Function, reloadReport: Function };

    setup() {
        this.orm = useService("orm");
        this.state = useState({ collapsedProducts: {} });
        this.opGuard = useOperationGuard();
        this._reserve = this.opGuard.guard(this._reserve.bind(this));
        this._unreserve = this.opGuard.guard(this._unreserve.bind(this));
        this._onClickChangePriority = this.opGuard.guard(
            this._onClickChangePriority.bind(this),
        );
        this._deriveLinesData(this.props.docs);
        onWillUpdateProps((nextProps) => this._deriveLinesData(nextProps.docs));

        this._formatFloat = (num) =>
            formatFieldFloat(num, { digits: [false, this.props.docs.precision] });
    }

    _deriveLinesData(docs) {
        this.docs = docs;
        this._prepareLines();
        this._indexLines();
        this._dropEmptyFreeStockLine();
        this._indexLines();
        this._computeTotals();
        this._mergeLines();
    }

    _prepareLines() {
        this._lines = [...this.docs.lines];
        if (this.multipleProducts) {
            this._lines.sort((a, b) => (a.product.id || 0) - (b.product.id || 0));
        }
    }

    _indexLines() {
        this._categoryByLine = new Map();
        this._linesByProduct = new Map();
        this._linesByProductCategory = new Map();
        this._outDocsByProductCategory = new Map();
        for (const line of this._lines) {
            const productId = line.product.id;
            const category = classifyLine(line);
            this._categoryByLine.set(line, category);
            push(this._linesByProduct, productId, line);
            if (!category) {
                continue;
            }
            const key = `${productId}|${category}`;
            push(this._linesByProductCategory, key, line);
            const outKey = documentKey(line.document_out);
            if (outKey) {
                let docs = this._outDocsByProductCategory.get(key);
                if (!docs) {
                    docs = new Set();
                    this._outDocsByProductCategory.set(key, docs);
                }
                docs.add(outKey);
            }
        }
    }

    _dropEmptyFreeStockLine() {
        for (const productId of this.productIds) {
            const all = this._linesByProduct.get(productId);
            const free = this.linesOf(productId, "freeStock");
            if (all?.length > 1 && free.length === 1 && free[0].quantity === 0) {
                this._lines.splice(this._lines.indexOf(free[0]), 1);
            }
        }
    }

    _computeTotals() {
        this.onHandTotalQty = {};
        this.availableOnHandTotalQty = {};
        for (const productId of this.productIds) {
            const onHand = this.linesOf(productId, "onHand");
            this.onHandTotalQty[productId] = onHand.reduce(
                (sum, line) => sum + line.quantity,
                0,
            );
            this.availableOnHandTotalQty[productId] = onHand.reduce(
                (sum, line) => sum + (line.reservation ? 0 : line.quantity),
                0,
            );
        }
    }

    _mergeLines() {
        const lines = this.lines;
        this.mergedRows = {};
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
            if (!this.mergedRows[lastIndex]) {
                this.mergedRows[lastIndex] = { rowcount: 1, tot_qty: line.quantity };
            }
            this.mergedRows[lastIndex].rowcount += 1;
            this.mergedRows[lastIndex].tot_qty += nextLine.quantity;
        }
    }

    _sameLineRule(line, nextLine) {
        const category = this.categoryOf(line);
        const sameCategory = category === this.categoryOf(nextLine);
        return (
            (this.sameDocumentIn(line, nextLine) &&
                line.receipt_date === nextLine.receipt_date) ||
            (sameCategory && (category === "onHand" || category === "notAvailable"))
        );
    }

    /** @returns {string | null} */
    categoryOf(line) {
        return this._categoryByLine.get(line) ?? null;
    }

    /** @returns {object[]} */
    linesOf(productId, category) {
        return this._linesByProductCategory.get(`${productId}|${category}`) || [];
    }

    isOnHand(line) {
        return this.categoryOf(line) === "onHand";
    }

    isReconciled(line) {
        return this.categoryOf(line) === "reconciled";
    }

    _coversSameDocumentOut(productId, category, line) {
        const outKey = documentKey(line.document_out);
        return Boolean(
            outKey &&
            this._outDocsByProductCategory.get(`${productId}|${category}`)?.has(outKey),
        );
    }

    displayReserve(line, lineIndex) {
        let splittedLine = true;
        if (lineIndex - 1 >= 0) {
            const previousLine = this.lines[lineIndex - 1];
            const productId = line.product.id;
            const isOnHandSplittedLine = this._coversSameDocumentOut(
                productId,
                "onHand",
                line,
            );
            const isReconciledSplittedLine =
                !this.isReconciled(line) &&
                this._coversSameDocumentOut(productId, "reconciled", line);
            splittedLine =
                productId === previousLine.product.id &&
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
        const key = documentKey(line1[docField]);
        return Boolean(key && key === documentKey(line2[docField]));
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

    get freeStockLabel() {
        return _t("Free Stock");
    }

    incomingSentence(line, quantity) {
        return _t("%(quantity)s %(uom)s expected on %(date)s", {
            quantity: this._formatFloat(quantity),
            uom: line.uom_id.display_name,
            date: line.receipt_date,
        });
    }

    stockToReserveSentence(line) {
        return _t("Stock To Reserve: %(quantity)s %(uom)s", {
            quantity: this._formatFloat(this.onHandTotalQty[line.product.id]),
            uom: line.uom_id.display_name,
        });
    }

    get lines() {
        return this._lines;
    }

    get multipleProducts() {
        return this.docs.multiple_product;
    }

    toggleProduct(productId) {
        this.state.collapsedProducts[productId] =
            !this.state.collapsedProducts[productId];
    }

    groupClass(productId) {
        if (!this.multipleProducts) {
            return "";
        }
        return this.state.collapsedProducts[productId] ? "collapse" : "collapse show";
    }

    get productIds() {
        return Object.keys(this.docs.product).map(Number);
    }
}

function push(map, key, value) {
    const bucket = map.get(key);
    if (bucket) {
        bucket.push(value);
    } else {
        map.set(key, [value]);
    }
}
