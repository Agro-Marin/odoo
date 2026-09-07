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
        // `getPageNumber` used to read `filteredOrdersCount` three times in one
        // template expression, and each read filters every order in the session,
        // fuzzy-matches the search term over the result and sorts it. A mount
        // renders twice, so four passes is two per render: the page slice and the
        // total, which want different things from one scan.
        //
        // The SYNCED filter takes neither path -- it reads screenState.totalCount
        // and a stored id list -- but that is not asserted here: onMounted kicks
        // onFilterSelected off inside a setTimeout whose RPC the mount does not
        // await, so the count depends on whether that timer has fired.
        expect(await scansForOneMount()).toBe(4);
    });
});
