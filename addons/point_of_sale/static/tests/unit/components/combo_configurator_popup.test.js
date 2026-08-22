import { animationFrame, expect, test } from "@odoo/hoot";
import { ComboConfiguratorPopup } from "@point_of_sale/app/components/popups/combo_configurator_popup/combo_configurator_popup";
import { getService, mountWithCleanup } from "@web/../tests/web_test_helpers";
import { MainComponentsContainer } from "@web/ui/main_components_container";

import { definePosModels } from "../data/generate_model_definitions.js";
import { setupPosEnv } from "../utils.js";

definePosModels();

function findComponent(node, name) {
    for (const child of Object.values(node.children)) {
        if (child.component?.constructor?.name === name) {
            return child.component;
        }
        const found = findComponent(child, name);
        if (found) {
            return found;
        }
    }
    return null;
}

const qtyInputValueFor = (productName) => {
    const article = [...document.querySelectorAll(".modal article")].find((el) =>
        el.textContent.includes(productName),
    );
    return article?.querySelector('input[name="pos_quantity"]')?.value;
};

test("combo item qty input reflects re-selection for a qty_max>1 combo", async () => {
    const store = await setupPosEnv();
    const productTemplate = store.models["product.template"].get(7);
    const root = await mountWithCleanup(MainComponentsContainer);
    getService("dialog").add(ComboConfiguratorPopup, {
        productTemplate,
        getPayload: () => {},
        close: () => {},
    });
    await animationFrame();
    const comp = findComponent(root.__owl__, "ComboConfiguratorPopup");
    expect(comp).not.toBe(null);

    const combo = store.models["product.combo"].get(1);
    combo.qty_max = 2;
    const comboItem = combo.combo_item_ids[0];
    const product = comboItem.product_id;

    comp.onClickProduct(product, comboItem);
    await animationFrame();
    expect(comp.state.qty[combo.id][comboItem.id]).toBe(1);
    expect(qtyInputValueFor(product.display_name)).toBe("1");

    comp.onClickProduct(product, comboItem);
    comp.onClickProduct(product, comboItem);
    await animationFrame();
    expect(comp.state.qty[combo.id][comboItem.id]).toBe(2);
    expect(qtyInputValueFor(product.display_name)).toBe("2");
});
