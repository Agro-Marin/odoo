import { expect, test } from "@odoo/hoot";
import { mockDate } from "@odoo/hoot-mock";
import { getFilledOrder, setupPosEnv } from "@point_of_sale/../tests/unit/utils";
import { definePosLoyaltyModels } from "@pos_loyalty/../tests/unit/data/generate_model_definitions";
import { ManageGiftCardPopup } from "@pos_loyalty/app/components/popups/manage_giftcard_popup/manage_giftcard_popup";
import { mountWithCleanup, onRpc } from "@web/../tests/web_test_helpers";

definePosLoyaltyModels();

test("addBalance", async () => {
    const store = await setupPosEnv();

    // Freeze current date so luxon.DateTime.now() is fixed
    mockDate("2025-01-01");

    let payloadResult = null;

    const order = await getFilledOrder(store);
    const popup = await mountWithCleanup(ManageGiftCardPopup, {
        props: {
            line: order.lines[0],
            title: "Sell/Manage physical gift card",
            getPayload: (code, amount, expDate) => {
                payloadResult = { code, amount, expDate };
            },
            close: () => {},
        },
    });

    popup.state.inputValue = "";
    popup.state.amountValue = "";
    const valid = popup.validateCode();

    expect(valid).toBe(false);
    expect(popup.state.error).toBe(true);

    popup.state.inputValue = "101";
    popup.state.amountValue = "100";
    popup.state.error = false;
    popup.state.amountError = false;

    await popup.addBalance();

    expect(payloadResult.code).toBe("101");
    expect(payloadResult.amount).toBe(100);
    // expiration is +1 year
    expect(payloadResult.expDate).toBe("2026-01-01");
});

test("checkGiftCard takes an existing card's balance as its amount", async () => {
    const store = await setupPosEnv();
    onRpc("loyalty.card", "get_gift_card_status", () => ({
        status: true,
        data: {
            "loyalty.card": [
                { id: 1, code: "gc-60", points: 60, expiration_date: false },
            ],
        },
    }));
    const order = await getFilledOrder(store);
    const popup = await mountWithCleanup(ManageGiftCardPopup, {
        props: {
            line: order.lines[0],
            title: "Sell/Manage physical gift card",
            getPayload: () => {},
            close: () => {},
        },
    });

    popup.state.inputValue = "gc-60";
    await popup.checkGiftCard();

    expect(popup.state.amountValue).toBe("60");
    expect(popup.state.lockGiftCardFields).toBe(true);
});
