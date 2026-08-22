import { expect, test } from "@odoo/hoot";
import { ProductCatalogKanbanModel } from "@product/product_catalog/kanban_model";
import { ProductCatalogOrderLine } from "@product/product_catalog/order_line/order_line";

/**
 * `_getSampleOrderLineInfo` stands in for `/product/catalog/order_lines_info`
 * when the view runs on sample data. `_loadData` indexes it by record id, so it
 * has to answer for every id it is handed -- a grouped sample read hands out
 * ids across the whole generated set, not just the first page of it, which is
 * what a payload generated over a fixed 1..N range got wrong.
 *
 * The contract under test is "answers for the ids given", so the ids here are
 * deliberately arbitrary and sparse: pinning them to the sample server's own
 * `MAIN_RECORDSET_SIZE` would restate in the test exactly the coupling the fix
 * removed from the code.
 */
const sampleInfoFor = (ids) =>
    ProductCatalogKanbanModel.prototype._getSampleOrderLineInfo.call({}, ids);

test("sample order line info answers for every id it is given", () => {
    const ids = [1, 2, 7, 11, 16, 23, 40];
    const info = sampleInfoFor(ids);
    expect(ids.filter((id) => !info[id]).join(",")).toBe("");
});

test("sample order line info only emits props the order line declares", () => {
    const declared = new Set(Object.keys(ProductCatalogOrderLine.props));
    const undeclared = Object.keys(sampleInfoFor([1])[1]).filter(
        (key) => !declared.has(key),
    );
    // A field owned by a downstream order line (min_qty, suggested_qty, ...) is
    // that module's to supply; emitting it here fails props validation on the
    // base component.
    expect(undeclared.join(",")).toBe("");
});

test("sample order line info is reproducible", () => {
    expect(sampleInfoFor([1, 2, 3])).toEqual(sampleInfoFor([1, 2, 3]));
});

test("grouped records are collected from every opened subgroup", () => {
    const collect = ProductCatalogKanbanModel.prototype._collectGroupedRecords;
    const groups = [
        { records: [{ id: 1 }] },
        { groups: [{ records: [{ id: 2 }, { id: 3 }] }, { records: [{ id: 4 }] }] },
    ];
    expect(
        collect
            .call({}, groups)
            .map((r) => r.id)
            .sort((a, b) => a - b),
    ).toEqual([1, 2, 3, 4]);
});
