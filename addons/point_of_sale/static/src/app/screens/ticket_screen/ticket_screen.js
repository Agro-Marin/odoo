/** @odoo-module native */
import { Component, onMounted, onWillStart, useState } from "@odoo/owl";
import { CenteredIcon } from "@point_of_sale/app/components/centered_icon/centered_icon";
import {
    BACKSPACE,
    DECIMAL,
    getButtons,
    Numpad,
    ZERO,
} from "@point_of_sale/app/components/numpad/numpad";
import { OrderDisplay } from "@point_of_sale/app/components/order_display/order_display";
import { Orderline } from "@point_of_sale/app/components/orderline/orderline";
import { NumberPopup } from "@point_of_sale/app/components/popups/number_popup/number_popup";
import { useTrackedAsync } from "@point_of_sale/app/hooks/hooks";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { PosOrderLineRefund } from "@point_of_sale/app/models/pos_order_line_refund";
import { ActionpadWidget } from "@point_of_sale/app/screens/product_screen/action_pad/action_pad";
import { BackButton } from "@point_of_sale/app/screens/product_screen/action_pad/back_button/back_button";
import { InvoiceButton } from "@point_of_sale/app/screens/ticket_screen/invoice_button/invoice_button";
import { SearchBar } from "@point_of_sale/app/screens/ticket_screen/search_bar/search_bar";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { BarcodeVideoScanner } from "@web/components/barcode";
import { parseDateTime } from "@web/core/l10n/dates";
import { luxon } from "@web/core/l10n/luxon";
import { ConnectionLostError } from "@web/core/network";
import { parseFloat } from "@web/core/parsers";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { fuzzyLookup } from "@web/core/utils/search";
import { AlertDialog } from "@web/ui/dialog";
const { DateTime } = luxon;
const NBR_BY_PAGE = 30;

export class TicketScreen extends Component {
    static storeOnOrder = false;
    static template = "point_of_sale.TicketScreen";
    static components = {
        ActionpadWidget,
        InvoiceButton,
        Orderline,
        OrderDisplay,
        CenteredIcon,
        SearchBar,
        Numpad,
        BackButton,
        BarcodeVideoScanner,
    };
    static props = {
        reuseSavedUIState: { type: Boolean, optional: true },
        stateOverride: { type: Object, optional: true },
    };
    static defaultProps = {
        reuseSavedUIState: false,
    };

    setup() {
        this.pos = usePos();
        this.ui = useService("ui");
        this.dialog = useService("dialog");
        this.numberBuffer = useService("number_buffer");
        this.doPrint = useTrackedAsync((_selectedSyncedOrder) =>
            this.print(_selectedSyncedOrder),
        );
        this.numberBuffer.use({
            triggerAtInput: (event) => this._onUpdateSelectedOrderline(event),
        });

        this.state = useState({
            nbrByPage: NBR_BY_PAGE,
            page: 1,
            nbrPage: 1,
            filter: null,
            search: this.pos.getDefaultSearchDetails(),
            selectedOrderUuid: this.pos.getOrder()?.uuid || null,
            selectedOrderlineIds: {},
            selectedPreset: null,
        });
        Object.assign(this.state, this.props.stateOverride || {});

        onMounted(this.onMounted);
        onWillStart(async () => {
            if (!this.pos.loadingOrderState) {
                try {
                    this.pos.loadingOrderState = true;
                    await this.pos.getServerOrders();
                } catch (error) {
                    if (error instanceof ConnectionLostError) {
                        return error;
                    }
                    throw error;
                } finally {
                    this.pos.loadingOrderState = false;
                }
            }
        });
    }
    onMounted() {
        setTimeout(() => {
            this.onFilterSelected(this.state.filter);
        });
    }
    async onClickPageNbr() {
        const nbr = await makeAwaitable(this.dialog, NumberPopup, {
            title: _t("Number by page"),
            isValid: (value) => value > 0 && value <= 100,
        });

        if (nbr && !isNaN(nbr)) {
            this.state.nbrByPage = parseInt(nbr);
            this.state.page = 1;
            if (this.state.filter === "SYNCED") {
                await this._fetchSyncedOrders();
            }
        }
    }
    async onPresetSelected(preset) {
        if (this.state.selectedPreset === preset) {
            this.state.selectedPreset = null;
        } else {
            this.state.selectedPreset = preset;
        }
        if (this.state.filter === "SYNCED") {
            this.state.page = 1;
            await this._fetchSyncedOrders();
        }
        if (this.state.selectedPreset) {
            const firstFilteredOrder = this.getFilteredOrderList()[0];
            if (firstFilteredOrder) {
                this.onClickOrder(firstFilteredOrder);
            }
        }
    }
    async print(order) {
        await this.pos.printReceipt({ order: order });
    }
    async onFilterSelected(selectedFilter) {
        this.state.filter = selectedFilter;
        this.state.page = 1;
        this.pos.screenState.ticketScreen.totalCount = 0;
        this.pos.screenState.ticketScreen.syncedPageOrderIds = [];

        if (this.state.filter === "SYNCED") {
            await this._fetchSyncedOrders();
        }
    }
    getNumpadButtons() {
        return getButtons(
            [{ value: "-", text: "+/-", disabled: true }, ZERO, DECIMAL],
            [
                { value: "quantity", text: _t("Qty"), class: "active border-primary" },
                { value: "discount", text: _t("% Disc"), disabled: true },
                { value: "price", text: _t("Price"), disabled: true },
                BACKSPACE,
            ],
        );
    }
    async onClickScanOrder(qrcode) {
        const invalidQrCode = () =>
            this.env.services.notification.add(
                _t("Invalid QR Code! Please, Scan again!"),
                { type: "warning" },
            );
        if (!qrcode) {
            this.env.services.notification.add(_t("Please, Scan again!"), {
                type: "warning",
            });
            return;
        }
        let uuid;
        try {
            uuid = new URL(qrcode).searchParams.get("order_uuid");
        } catch {
            invalidQrCode();
            return;
        }
        const orders = await this.pos.data.loadServerOrders([["uuid", "=", uuid]]);
        const order = orders[0];
        if (order) {
            this.state.filter = "SYNCED";
            this.setSelectedOrder(order);
            this.pos.scanning = false;
        } else {
            invalidQrCode();
        }
    }
    async onSearch(search) {
        this.state.search = search;
        this.state.page = 1;
        if (this.state.filter === "SYNCED") {
            await this._fetchSyncedOrders();
        }
    }
    onClickOrder(clickedOrder) {
        this.setSelectedOrder(clickedOrder);
        this.numberBuffer.reset();
        if (
            (!clickedOrder || clickedOrder.finalized) &&
            !this.getSelectedOrderlineId()
        ) {
            const firstLine = this.getSelectedOrder().getOrderlines()[0];
            if (firstLine) {
                this.state.selectedOrderlineIds[clickedOrder.id] = firstLine.id;
            }
        }
    }
    onDblClickOrder(order) {
        if (!order.finalized) {
            this.setOrder(order);
        }
    }
    async onClickReprintAll(order) {
        const printingChanges = order.uiState?.lastPrints;
        if (printingChanges) {
            await this.pos.printChanges(order, printingChanges, true);
        }
    }
    async onNextPage() {
        if (this.state.page < this.getNbrPages()) {
            this.state.page += 1;
            if (this.state.filter === "SYNCED") {
                await this._fetchSyncedOrders();
            }
        }
    }
    async onPrevPage() {
        if (this.state.page > 1) {
            this.state.page -= 1;
            if (this.state.filter === "SYNCED") {
                await this._fetchSyncedOrders();
            }
        }
    }
    async onInvoiceOrder(orderId) {
        const order = this.pos.models["pos.order"].get(orderId);
        this.setSelectedOrder(order);
    }
    onClickOrderline(orderline) {
        if (this.getSelectedOrder()?.finalized) {
            this.numberBuffer.capture();
            const order = this.getSelectedOrder();
            this.state.selectedOrderlineIds[order.id] = orderline.id;
            this.numberBuffer.reset();
        }
    }
    onClickRefundOrderUid(orderUuid) {
        const refundOrder = this.pos.models["pos.order"].find(
            (order) => order.uuid === orderUuid,
        );
        if (refundOrder) {
            this.setOrder(refundOrder);
        }
    }
    _setToRefundDetail(toRefundDetail, buffer) {
        if (toRefundDetail.destinationOrder) {
            return this.numberBuffer.reset();
        }

        toRefundDetail.refundableQty =
            toRefundDetail.line.qty - toRefundDetail.line.refundedQty;
        if (toRefundDetail.refundableQty <= 0) {
            return this.numberBuffer.reset();
        }

        if (buffer == null || buffer === "") {
            toRefundDetail.qty = 0;
        } else {
            const quantity = Math.abs(parseFloat(buffer));
            if (quantity > toRefundDetail.refundableQty) {
                this.numberBuffer.reset();
                if (!toRefundDetail.line.combo_parent_id) {
                    this.dialog.add(AlertDialog, {
                        title: _t("Maximum Exceeded"),
                        body: _t(
                            "The requested quantity to be refunded is higher than the ordered quantity. %s is requested while only %s can be refunded.",
                            quantity,
                            toRefundDetail.refundableQty,
                        ),
                    });
                }
            } else {
                toRefundDetail.qty = quantity;
            }
        }
    }
    _onUpdateSelectedOrderline({ key, buffer }) {
        const order = this.getSelectedOrder();
        if (!order) {
            return this.numberBuffer.reset();
        }

        const selectedOrderlineId = this.getSelectedOrderlineId();
        let orderline = order.lines.find((line) => line.id === selectedOrderlineId);
        if (!orderline) {
            return this.numberBuffer.reset();
        }

        if (!orderline.isPartOfCombo()) {
            const toRefundDetail = this.getToRefundDetail(orderline);
            this._setToRefundDetail(toRefundDetail, buffer);
            return;
        }

        if (orderline.combo_parent_id) {
            orderline = orderline.combo_parent_id;
        }

        const parentToRefundDetail = this.getToRefundDetail(orderline);
        this._setToRefundDetail(parentToRefundDetail, buffer);

        for (const comboLine of orderline.combo_line_ids) {
            const toRefundDetail = this.getToRefundDetail(comboLine);
            toRefundDetail.qty =
                (comboLine.qty / orderline.qty) * parentToRefundDetail.qty;
        }
    }
    async addAdditionalRefundInfo(order, destinationOrder) {
        return Promise.resolve();
    }
    async _doneOrder(order) {
        return;
    }
    async onDoRefund() {
        this.numberBuffer.capture();
        const order = this.getSelectedOrder();

        if (order && this._doesOrderHaveSoleItem(order)) {
            if (!this._prepareAutoRefundOnOrder(order)) {
                return;
            }
        }

        if (!order || !this.getHasItemsToRefund()) {
            return;
        }

        if (order.fiscal_position_not_found) {
            this.dialog.add(AlertDialog, {
                title: _t("Fiscal Position not found"),
                body: _t(
                    "The fiscal position used in the original order is not loaded. Make sure it is loaded by adding it in the pos configuration.",
                ),
            });
            return;
        }

        const partner = order.getPartner();
        const refundableDetails = this._getRefundableDetails(partner, order);
        if (refundableDetails.length === 0) {
            return;
        }
        const destinationOrder = this._getEmptyOrder(partner);

        destinationOrder.is_refund = true;
        destinationOrder.pricelist_id = order.pricelist_id;
        const lines = [];
        for (const refundDetail of refundableDetails) {
            const refundLine = refundDetail.line;
            const alreadyRefundedLots = refundLine.refund_orderline_ids
                .filter((item) => !["cancel", "draft"].includes(item.order_id.state))
                .flatMap((item) => item.pack_lot_ids)
                .map((pack_lot) => pack_lot.lot_name);
            const options = refundLine.pack_lot_ids
                .map((p) => p.lot_name)
                .filter((lotName) => !alreadyRefundedLots.includes(lotName));
            const line = this.pos.models["pos.order.line"].create({
                qty: -refundDetail.qty,
                price_unit: refundLine.price_unit,
                product_id: refundLine.product_id,
                order_id: destinationOrder,
                discount: refundLine.discount,
                tax_ids: refundLine.tax_ids.map((tax) => ["link", tax]),
                refunded_orderline_id: refundLine,
                pack_lot_ids: options
                    .slice(0, refundDetail.qty)
                    .map((lotName) => ["create", { lot_name: lotName }]),
                price_type: "automatic",
                attribute_value_ids: refundLine.attribute_value_ids.map((attr) => [
                    "link",
                    attr,
                ]),
            });
            lines.push(line);
            refundDetail.destination_order_uuid = destinationOrder.uuid;
        }
        const refundComboParentLines = lines.filter(
            (l) => l.refunded_orderline_id.combo_line_ids.length > 0,
        );
        for (const refundComboParent of refundComboParentLines) {
            const children = refundComboParent.refunded_orderline_id.combo_line_ids
                .map((l) => l.refund_orderline_ids)
                .flat();
            refundComboParent.combo_line_ids = [["link", ...children]];
        }

        if (order.fiscal_position_id) {
            destinationOrder.fiscal_position_id = order.fiscal_position_id;
        }
        this.setPartnerToRefundOrder(partner, destinationOrder);
        destinationOrder.refunded_order_id = order;
        this.pos.setOrder(destinationOrder);
        await this.addAdditionalRefundInfo(order, destinationOrder);

        this.postRefund(destinationOrder);
        this.pos.ticket_screen_mobile_pane = "left";
        destinationOrder.setScreenData({ name: "PaymentScreen" });
        this.pos.navigate("PaymentScreen", { orderUuid: destinationOrder.uuid });
    }

    async onDeleteOrder(order) {
        await this.pos.onDeleteOrder(order);
        this.setSelectedOrder(this.pos.getOrder());
    }

    postRefund(destinationOrder) {}

    setPartnerToRefundOrder(partner, destinationOrder) {
        if (partner && !destinationOrder.getPartner()) {
            destinationOrder.setPartner(partner);
        }
    }
    setSelectedOrder(order) {
        this.state.selectedOrderUuid = order?.uuid || null;
    }
    getSelectedOrder() {
        return (
            this.pos.models["pos.order"].getBy("uuid", this.state.selectedOrderUuid) ||
            null
        );
    }
    getSelectedOrderlineId() {
        if (this.getSelectedOrder()) {
            return this.state.selectedOrderlineIds[this.getSelectedOrder().id];
        }
    }
    get isOrderSynced() {
        return (
            this.getSelectedOrder()?.finalized &&
            (this.getSelectedOrder().getScreenData().name === "" ||
                this.state.filter === "SYNCED")
        );
    }
    activeOrderFilter(o) {
        const screen = ["ReceiptScreen", "TipScreen"];
        const oScreen = o.getScreenData();
        return (!o.finalized || screen.includes(oScreen.name)) && o.uiState.displayed;
    }
    _getFilteredOrders() {
        const orderModel = this.pos.models["pos.order"];
        let orders =
            this.state.filter === "SYNCED"
                ? orderModel.filter((o) => o.finalized && o.uiState.displayed)
                : orderModel.filter(this.activeOrderFilter);

        if (
            this.state.filter &&
            !["ACTIVE_ORDERS", "SYNCED"].includes(this.state.filter)
        ) {
            orders = orders.filter((order) => {
                const screen = order.getScreenData();
                return this._getScreenToStatusMap()[screen.name] === this.state.filter;
            });
        }

        if (this.state.search.searchTerm) {
            const repr = this._getSearchFields()[this.state.search.fieldName].repr;
            orders = fuzzyLookup(this.state.search.searchTerm, orders, repr);
        }
        if (this.state.search.partnerId && this.state.search.fieldName === "PARTNER") {
            orders = orders.filter(
                (order) => order.partner_id?.id === this.state.search.partnerId,
            );
        }

        if (this.state.selectedPreset) {
            orders = orders.filter(
                (order) => order.preset_id?.id === this.state.selectedPreset.id,
            );
        }

        const ascending = this.state.filter !== "SYNCED";
        return orders.sort((a, b) => {
            const dateA = a.date_order;
            const dateB = b.date_order;
            if (!dateA.equals(dateB)) {
                return ascending ? dateA - dateB : dateB - dateA;
            }
            const nameA = parseInt(a.pos_reference.replace(/\D/g, "")) || 0;
            const nameB = parseInt(b.pos_reference.replace(/\D/g, "")) || 0;
            return ascending ? nameA - nameB : nameB - nameA;
        });
    }

    getFilteredOrderList() {
        if (this.state.filter === "SYNCED") {
            return this.pos.models["pos.order"]
                .readMany(this.pos.screenState.ticketScreen.syncedPageOrderIds || [])
                .filter(Boolean);
        }
        return this._getFilteredOrders().slice(
            (this.state.page - 1) * this.state.nbrByPage,
            this.state.page * this.state.nbrByPage,
        );
    }

    get filteredOrdersCount() {
        return this.state.filter === "SYNCED"
            ? this.pos.screenState.ticketScreen.totalCount
            : this._getFilteredOrders().length;
    }
    getDate(order) {
        return this.pos.getDate(order.date_order);
    }
    getTotal(order) {
        return this.env.utils.formatCurrency(order.priceIncl);
    }
    getPartner(order) {
        return order.getPartnerName();
    }
    getCardholderName(order) {
        return order.getCardHolderName();
    }
    getCashier(order) {
        return order.employee_id ? order.employee_id.name : "";
    }
    getStatus(order) {
        if (
            order.finalized &&
            (order.getScreenData().name === "" || this.state.filter === "SYNCED")
        ) {
            return _t("Paid");
        } else {
            const screen = order.getScreenData();
            return this._getOrderStates().get(this._getScreenToStatusMap()[screen.name])
                ?.text;
        }
    }
    isDefaultOrderEmpty(order) {
        const status = this._getScreenToStatusMap()[order.getScreenData().name];
        const productScreenStatus = this._getScreenToStatusMap().ProductScreen;
        return (
            order.getOrderlines().length === 0 &&
            this.pos.getOpenOrders().length === 1 &&
            status === productScreenStatus &&
            order.payment_ids.length === 0
        );
    }
    shouldHideDeleteButton(order) {
        const orders = this.pos.models["pos.order"].filter((o) => !o.finalized);
        return (
            (orders.length === 1 && orders[0].lines.length === 0) ||
            (this.ui.isSmall && order !== this.getSelectedOrder()) ||
            this.isDefaultOrderEmpty(order) ||
            order.finalized ||
            order.payment_ids.some(
                (payment) =>
                    payment.isElectronic() && payment.getPaymentStatus() === "done",
            )
        );
    }
    isHighlighted(order) {
        const selectedOrder = this.getSelectedOrder();
        return selectedOrder ? order.id && order.id === selectedOrder.id : false;
    }
    showCardholderName() {
        return this.pos.models["pos.payment.method"].some(
            (method) => method.use_payment_terminal,
        );
    }
    getSearchBarConfig() {
        return {
            searchFields: new Map(
                Object.entries(this._getSearchFields()).map(([key, val]) => [
                    key,
                    val.displayName,
                ]),
            ),
            filter: { show: true, options: this._getFilterOptions() },
            defaultSearchDetails: this.state.search,
            defaultFilter: this.state.filter,
        };
    }
    getNbrPages() {
        return Math.ceil(this.filteredOrdersCount / this.state.nbrByPage);
    }
    getPageNumber() {
        if (!this.filteredOrdersCount) {
            return `0/0`;
        } else {
            return `${(this.state.page - 1) * this.state.nbrByPage + 1}-${Math.min(
                this.state.page * this.state.nbrByPage,
                this.filteredOrdersCount,
            )} / ${this.filteredOrdersCount}`;
        }
    }
    getHasItemsToRefund() {
        const order = this.getSelectedOrder();
        if (!order) {
            return false;
        }
        if (this._doesOrderHaveSoleItem(order)) {
            return true;
        }
        const total = Object.values(order.uiState.lineToRefund).reduce((acc, val) => {
            acc += val.qty;
            return acc;
        }, 0);

        return !this.pos.isProductQtyZero(total);
    }
    switchPane() {
        this.pos.switchPaneTicketScreen();
    }
    /**
     * @param {Object | null} partner
     * @returns {boolean}
     */
    _getEmptyOrder(partner) {
        let emptyOrderForPartner = null;
        let emptyOrder = null;
        for (const order of this.pos.models["pos.order"].filter(
            (order) => !order.finalized,
        )) {
            if (order.getOrderlines().length === 0 && order.payment_ids.length === 0) {
                if (order.getPartner() === partner) {
                    emptyOrderForPartner = order;
                    break;
                } else if (!order.getPartner() && emptyOrder === null) {
                    emptyOrder = order;
                }
            }
        }
        return (
            emptyOrderForPartner ||
            emptyOrder ||
            this.pos.addNewOrder({ partner_id: partner })
        );
    }
    _doesOrderHaveSoleItem(order) {
        const orderlines = order.getOrderlines();
        if (orderlines.length !== 1) {
            return false;
        }
        const theOrderline = orderlines[0];
        const refundableQty = theOrderline.getQuantity() - theOrderline.refundedQty;
        return this.pos.isProductQtyZero(refundableQty - 1);
    }
    _prepareAutoRefundOnOrder(order) {
        const selectedOrderlineId = this.getSelectedOrderlineId();
        const orderline = order.lines.find((line) => line.id === selectedOrderlineId);
        if (!orderline) {
            return false;
        }

        const toRefundDetail = this.getToRefundDetail(orderline);
        if (
            this.pos.isProductQtyZero(toRefundDetail.maxQty - 1) &&
            toRefundDetail.qty === 0
        ) {
            toRefundDetail.qty = 1;
        }
        return true;
    }
    /**
     * @param {models.Orderline} orderline
     */
    getToRefundDetail(orderline) {
        const lineToRefund = orderline.order_id.uiState.lineToRefund;

        if (orderline.uuid in lineToRefund) {
            return lineToRefund[orderline.uuid];
        }

        const newToRefundDetail = new PosOrderLineRefund(
            {
                line_uuid: orderline.uuid,
                qty: 0,
            },
            this.pos.models,
        );

        lineToRefund[orderline.uuid] = newToRefundDetail;
        return newToRefundDetail;
    }
    /**
     * @param {Object} partner
     * @param {Order} order
     * @returns {Array}
     */
    _getRefundableDetails(partner, order) {
        return Object.values(this.pos.linesToRefund).filter(
            (refund) =>
                !this.pos.isProductQtyZero(refund.qty) &&
                refund.line.order_id.uuid === order.uuid &&
                (partner ? refund.line.order_id.partner_id?.id === partner.id : true) &&
                !refund.destinationOrder,
        );
    }

    async setOrder(order) {
        if (this.pos.config.isShareable) {
            await this.pos.syncAllOrders();
        }
        this.pos.setOrder(order);
        this.pos.navigateToOrderScreen(order);
    }

    onClickNewOrder() {
        const order = this.pos.createNewOrder({
            preset_id: this.state.selectedPreset || null,
        });
        this.pos.selectedOrderUuid = order.uuid;
        this.pos.addPendingOrder([order.id]);
        this.pos.navigateToOrderScreen(order);
    }

    _getFilterOptions() {
        const orderStates = this._getOrderStates();
        orderStates.set("SYNCED", { text: _t("Paid") });
        return orderStates;
    }
    /**
     * @returns {Record<string, { repr: (order: models.Order) => string, displayName: string, modelFields: Array }>}
     */
    _getSearchFields() {
        const fields = {
            REFERENCE: {
                repr: (order) => order.getName(),
                displayName: _t("Reference"),
                modelFields: ["tracking_number", "floating_order_name"],
            },
            RECEIPT_NUMBER: {
                repr: (order) => order.pos_reference,
                displayName: _t("Receipt Number"),
                modelFields: ["pos_reference"],
            },
            INVOICE_NUMBER: {
                repr: (order) => order.invoiceName,
                displayName: _t("Invoice Number"),
                modelFields: ["account_move.name"],
            },
            DATE: {
                repr: (order) => this.getDate(order),
                displayName: _t("Date"),
                modelFields: ["date_order"],
                formatSearch: (searchTerm) => {
                    const includesTime = searchTerm.includes(":");
                    let parsedDateTime;
                    try {
                        parsedDateTime = parseDateTime(searchTerm);
                    } catch {
                        return searchTerm;
                    }
                    if (includesTime) {
                        return parsedDateTime.toUTC().toFormat("yyyy-MM-dd HH:mm:ss");
                    } else {
                        return parsedDateTime.toFormat("yyyy-MM-dd");
                    }
                },
            },
            PARTNER: {
                repr: (order) => order.getPartnerName(),
                displayName: _t("Customer"),
                modelFields: ["partner_id.complete_name"],
            },
        };

        if (this.showCardholderName()) {
            fields.CARDHOLDER_NAME = {
                repr: (order) => order.getCardHolderName(),
                displayName: _t("Cardholder Name"),
                modelFields: ["payment_ids.cardholder_name"],
            };
        }

        return fields;
    }
    _getScreenToStatusMap() {
        return {
            ProductScreen: "ONGOING",
            PaymentScreen: "PAYMENT",
            ReceiptScreen: "RECEIPT",
        };
    }
    _getOrderStates() {
        const states = new Map();
        states.set("ACTIVE_ORDERS", {
            text: _t("Active"),
        });
        states.set("ONGOING", {
            text: _t("Ongoing"),
            indented: true,
        });
        states.set("PAYMENT", {
            text: _t("Payment"),
            indented: true,
        });
        states.set("RECEIPT", {
            text: _t("Receipt"),
            indented: true,
        });
        return states;
    }
    _computeSyncedOrdersDomain() {
        const domain = [];
        if (this.state.search.partnerId && this.state.search.fieldName === "PARTNER") {
            domain.push(["partner_id.id", "in", [this.state.search.partnerId]]);
        }
        if (this.state.selectedPreset) {
            domain.push(["preset_id", "=", this.state.selectedPreset.id]);
        }
        let { fieldName, searchTerm } = this.state.search;
        const searchField = this._getSearchFields()[fieldName];
        if (searchTerm && searchField?.modelFields?.length > 0) {
            if (searchField.formatSearch) {
                searchTerm = searchField.formatSearch(searchTerm);
            }
            const orChain = [];
            for (const modelField of searchField.modelFields) {
                orChain.unshift([modelField, "ilike", `%${searchTerm}%`]);
                if (orChain.length > 1) {
                    orChain.unshift("|");
                }
            }
            domain.push(...orChain);
        }
        return domain;
    }
    async _fetchSyncedOrders() {
        const screenState = this.pos.screenState.ticketScreen;
        const domain = this._computeSyncedOrdersDomain();
        const offset = (this.state.page - 1) * this.state.nbrByPage;
        const config_id = this.pos.config.id;
        const { ordersInfo, totalCount } = await this.pos.data.call(
            "pos.order",
            "search_paid_order_ids",
            [],
            {
                config_id,
                domain,
                limit: this.state.nbrByPage,
                offset,
            },
        );

        screenState.totalCount = totalCount;
        screenState.syncedPageOrderIds = ordersInfo.map((info) => info[0]);

        const idsNotInCacheOrOutdated = ordersInfo
            .filter((orderInfo) => {
                const order = this.pos.models["pos.order"].get(orderInfo[0]);

                if (
                    order &&
                    parseDateTime(orderInfo[1], { tz: "UTC" }).setZone("local").ts >
                        order.date_order.ts
                ) {
                    return true;
                }

                return !order;
            })
            .map((info) => info[0]);

        if (idsNotInCacheOrOutdated.length > 0) {
            await this.pos.data.loadServerOrders([
                ["id", "in", Array.from(new Set(idsNotInCacheOrOutdated))],
            ]);
        }
    }
    getPresetTimeColor(order) {
        const slot = order.preset_id.currentSlot;
        const presetTime = order.preset_time;
        if (!slot) {
            if (presetTime < DateTime.now()) {
                return "bg-danger text-white";
            } else {
                return "bg-light text-emphasis";
            }
        }
        if (
            slot.datetime <= presetTime &&
            presetTime < slot.datetime.plus({ minutes: order.preset_id.interval_time })
        ) {
            return "bg-warning text-white";
        } else if (presetTime < slot.datetime) {
            return "bg-danger text-white";
        } else {
            return "bg-light text-emphasis";
        }
    }
}

registry.category("pos_pages").add("TicketScreen", {
    name: "TicketScreen",
    component: TicketScreen,
    route: `/pos/ui/${odoo.pos_config_id}/ticket`,
    params: {},
});
