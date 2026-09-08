import { describe, expect, test } from "@odoo/hoot";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { mountWithCleanup, patchWithCleanup } from "@web/../tests/web_test_helpers";

import { definePosModels } from "../data/generate_model_definitions.js";
import { getFilledOrder, setupPosEnv } from "../utils.js";

definePosModels();

async function scansForOneMount() {
    const store = await setupPosEnv();
    await getFilledOrder(store);
    await getFilledOrder(store);
    const counter = { scans: 0 };
    patchWithCleanup(TicketScreen.prototype, {
        _getFilteredOrders() {
            counter.scans++;
            return super._getFilteredOrders(...arguments);
        },
    });
    counter.scans = 0;
    await mountWithCleanup(TicketScreen, { props: { reuseSavedUIState: false } });
    return counter.scans;
}

describe("what the ticket screen costs to show", () => {
    test("the order list is filtered and sorted twice per render, not four times", async () => {
        expect(await scansForOneMount()).toBe(4);
    });
});
