import { expect, test } from "@odoo/hoot";
import { animationFrame, click } from "@odoo/hoot-dom";
import { ProductCatalogPurchaseOrderLine } from "@purchase/product_catalog/purchase_order_line/purchase_order_line";
import { PurchaseDashBoard } from "@purchase/views/purchase_dashboard";
import {
    defineModels,
    defineWebModels,
    fields,
    makeMockEnv,
    models,
    mountView,
    mountWithCleanup,
    onRpc,
} from "@web/../tests/web_test_helpers";

class PurchaseOrder extends models.Model {
    _name = "purchase.order";
    name = fields.Char();
    _records = [{ id: 7, name: "P0007" }];
}

defineWebModels();
defineModels([PurchaseOrder]);

function dashboardData() {
    const zero = () => ({ all: 0, priority: 0 });
    const side = () => ({
        draft: zero(),
        sent: zero(),
        late: zero(),
        not_acknowledged: zero(),
        late_receipt: zero(),
        days_to_order: 0,
    });
    return { global: side(), my: side(), days_to_purchase: 0, multiuser: false };
}

async function mountDashboard() {
    onRpc("purchase.order", "prepare_dashboard", () => dashboardData());
    const toggled = [];
    const searchModel = {
        query: [{ searchItemId: 99 }],
        context: {},
        getSearchItems: (predicate) =>
            [
                { id: 1, name: "draft_rfqs" },
                { id: 2, name: "my_purchases" },
                { id: 3, name: "waiting_rfqs" },
            ].filter(predicate),
        clearQuery() {
            this.query = [];
        },
        toggleSearchItem: (id) => toggled.push(id),
    };
    const env = await makeMockEnv({ searchModel });
    const board = await mountWithCleanup(PurchaseDashBoard, { env });
    return { board, searchModel, toggled };
}

test("an unknown filter name throws instead of silently clearing the query", async () => {
    const { board, searchModel, toggled } = await mountDashboard();
    expect(() => board.setSearchContext(["no_such_filter"])).toThrow(
        /no search filter named no_such_filter/,
    );
    expect(searchModel.query).toEqual([{ searchItemId: 99 }], {
        message: "the query is left alone when the card cannot be honoured",
    });
    expect(toggled).toEqual([]);
});

test("the RFQ Sent card resolves and applies waiting_rfqs", async () => {
    const { board, searchModel, toggled } = await mountDashboard();
    board.setSearchContext(["waiting_rfqs"]);
    expect(searchModel.query).toEqual([], { message: "cleared through clearQuery()" });
    expect(toggled).toEqual([3]);
});

test("a my-scoped card applies its own filter alongside my_purchases", async () => {
    const { board, toggled } = await mountDashboard();
    board.setSearchContext(["waiting_rfqs", "my_purchases"]);
    expect([...toggled].sort()).toEqual([2, 3]);
});

test("every dashboard card names at least one filter", async () => {
    const { board } = await mountDashboard();
    for (const card of board.cards.filter((c) => !c.spacer)) {
        expect(card.filters.length).toBeGreaterThan(0, {
            message: `card ${card.key} must map to a search filter`,
        });
    }
});

test("a failing prepare_dashboard degrades to a hidden strip", async () => {
    onRpc("purchase.order", "prepare_dashboard", () => {
        throw new Error("AccessDenied");
    });
    const env = await makeMockEnv({ searchModel: { query: [], context: {} } });
    const board = await mountWithCleanup(PurchaseDashBoard, { env });
    await animationFrame();
    expect(board.purchaseData).toBe(null);
    expect(document.querySelector(".o_purchase_dashboard")).toBe(null);
});

test("toaster_button sends once per click even when clicked twice", async () => {
    let calls = 0;
    let releaseCall;
    onRpc("purchase.order", "send_reminder_preview", async () => {
        calls++;
        await new Promise((resolve) => {
            releaseCall = resolve;
        });
        return { toast_message: "sent", toast_type: "success" };
    });
    await mountView({
        type: "form",
        resModel: "purchase.order",
        resId: 7,
        arch: `<form>
                 <field name="name"/>
                 <widget name="toaster_button" button_name="send_reminder_preview" title="Preview"/>
               </form>`,
    });
    const btn = document.querySelector("button[name=send_reminder_preview]");
    expect(btn).not.toBe(null);
    await click(btn);
    await animationFrame();
    expect(btn.disabled).toBe(true, {
        message: "disabled while the send is in flight",
    });
    await click(btn);
    await animationFrame();
    expect(calls).toBe(1, {
        message: "the second click does not send a second mail",
    });
    releaseCall();
    await animationFrame();
});

test("purchase catalog line declares only props the server actually sends", () => {
    expect("packaging" in ProductCatalogPurchaseOrderLine.props).toBe(false, {
        message: "no catalog payload has ever emitted a packaging key",
    });
    expect("min_qty" in ProductCatalogPurchaseOrderLine.props).toBe(true, {
        message: "min_qty is emitted whenever a seller is found, so it must stay",
    });
    expect(
        Object.getOwnPropertyDescriptor(
            ProductCatalogPurchaseOrderLine.prototype,
            "highlightUoM",
        ),
    ).toBe(undefined, { message: "highlightUoM was read by nothing" });
});
