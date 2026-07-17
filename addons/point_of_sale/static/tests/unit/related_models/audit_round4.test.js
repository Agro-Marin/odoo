import { expect, test } from "@odoo/hoot";
import { uuidv4 } from "@point_of_sale/utils";
import { makeMockServer } from "@web/../tests/web_test_helpers";
import { effect } from "@web/core/utils/reactive";

import { definePosModels } from "../data/generate_model_definitions.js";
import { getRelatedModelsInstance } from "../data/get_model_definitions.js";

definePosModels();

test("changing an indexed value re-keys the index with the old value", async () => {
    await makeMockServer();
    const models = getRelatedModelsInstance(false);
    const p1 = models["res.partner"].create({ id: 1, name: "A", barcode: "AAA" });
    const p2 = models["res.partner"].create({ id: 2, name: "B", barcode: "BBB" });

    // The re-index used to run AFTER the raw mutation: remove() walked the
    // NEW value, evicting p2 from "BBB" while "AAA" kept pointing at p1.
    p1.update({ barcode: "CCC" });
    expect(models["res.partner"].getBy("barcode", "AAA")).toBe(undefined);
    expect(models["res.partner"].getBy("barcode", "CCC").id).toBe(1);
    expect(models["res.partner"].getBy("barcode", "BBB").id).toBe(2);
    expect(p2.barcode).toBe("BBB");
});

test("update-only loads fire no create event", async () => {
    await makeMockServer();
    const models = getRelatedModelsInstance(false);
    const sampleUUID = uuidv4();
    models.loadConnectedData({
        "pos.order": [{ id: 21, uuid: sampleUUID, amount_total: 5 }],
    });

    let createEvents = 0;
    models["pos.order"].addEventListener("create", () => createEvents++);
    models.loadConnectedData({
        "pos.order": [{ id: 21, uuid: sampleUUID, amount_total: 9 }],
    });
    expect(createEvents).toBe(0);
});

test("record mutations made by load listeners are marked dirty", async () => {
    await makeMockServer();
    const models = getRelatedModelsInstance(false);
    const sampleUUID = uuidv4();
    models.loadConnectedData({
        "pos.order": [{ id: 22, uuid: sampleUUID, amount_total: 5 }],
    });

    // Events used to fire while _loadingData was still true, so a listener
    // reacting to a load by mutating a record (e.g. the pricelist-item
    // listener repricing orders) had its _markDirty silently swallowed.
    let listenerRan = false;
    models["pos.order"].addEventListener("update", ({ id }) => {
        const rec = models["pos.order"].get(id);
        if (!listenerRan) {
            listenerRan = true;
            rec.general_customer_note = "listener wrote this";
        }
    });
    models.loadConnectedData({
        "pos.order": [{ id: 22, uuid: sampleUUID, amount_total: 9 }],
    });
    expect(listenerRan).toBe(true);
    const order = models["pos.order"].get(22);
    expect(order.general_customer_note).toBe("listener wrote this");
    expect(order.isDirty()).toBe(true);
});

test("backLink results are reactive on a warm cache", async () => {
    await makeMockServer();
    const models = getRelatedModelsInstance(false);
    const order = models["pos.order"].create({ id: 31 });
    const att = models["product.template.attribute.value"].create({ id: 99 });
    models["pos.order.line"].create({
        id: 310,
        order_id: order,
        attribute_value_ids: [["link", att]],
    });

    // Warm the cache outside any reactive context.
    expect(att.backLink("<-pos.order.line.attribute_value_ids")).toHaveLength(1);

    // A reactive consumer reading the warm cache used to subscribe to
    // nothing — it never recomputed when the relation changed.
    let seen = 0;
    effect(
        (a) => {
            seen = a.backLink("<-pos.order.line.attribute_value_ids").length;
        },
        [att],
    );
    expect(seen).toBe(1);
    models["pos.order.line"].create({
        id: 311,
        order_id: order,
        attribute_value_ids: [["link", att]],
    });
    expect(seen).toBe(2);
});
