import { animationFrame, expect, test } from "@odoo/hoot";
import { queryAll } from "@odoo/hoot-dom";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import { MainComponentsContainer } from "@web/ui/main_components_container";

import { definePosModels } from "../data/generate_model_definitions.js";
import { setupPosEnv } from "../utils.js";

definePosModels();

test("the preset selection popup paints each preset in its configured colour", async () => {
    const store = await setupPosEnv();
    store.addNewOrder();
    store.models["pos.preset"].get(1).color = 3;

    await mountWithCleanup(MainComponentsContainer);
    store.selectPreset();
    await animationFrame();

    const items = queryAll(".selection-item");
    expect(items.length).toBeGreaterThan(1);
    expect(items[0]).toHaveClass("o_colorlist_item_color_3");
    // Every other caller of SelectionPopup passes no colour at all, so an item
    // without one must emit no colour class rather than
    // `o_colorlist_item_color_undefined`.
    expect(queryAll(".selection-item[class*='o_colorlist_item_color_']")).toHaveLength(
        1,
    );
});
