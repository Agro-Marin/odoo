import { describe, expect, test } from "@odoo/hoot";
import { queryAllTexts } from "@odoo/hoot-dom";
import {
    clickFieldDropdown,
    contains,
    defineModels,
    fields,
    models,
    mountView,
    onRpc,
} from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");

// UoM records shared by every test. `factor`/`parent_path` are stored
// server-side in real life; here they are static so the search mock is
// deterministic. Two independent chains: Units (root "1") and grams (root "10").
const UOM_ROWS = {
    1: {
        id: 1,
        display_name: "Units",
        relative_factor: 1,
        factor: 1,
        relative_uom_id: false,
        parent_path: "1/",
    },
    2: {
        id: 2,
        display_name: "Dozen",
        relative_factor: 12,
        factor: 12,
        relative_uom_id: [1, "Units"],
        parent_path: "1/2/",
    },
    3: {
        id: 3,
        display_name: "Pack of 6",
        relative_factor: 6,
        factor: 6,
        relative_uom_id: [1, "Units"],
        parent_path: "1/3/",
    },
    10: {
        id: 10,
        display_name: "g",
        relative_factor: 1,
        factor: 1,
        relative_uom_id: false,
        parent_path: "10/",
    },
    11: {
        id: 11,
        display_name: "kg",
        relative_factor: 1000,
        factor: 1000,
        relative_uom_id: [10, "g"],
        parent_path: "10/11/",
    },
};
const COMMON_ROOT_IDS = [1, 2, 3]; // share root "1/"
const OTHER_IDS = [10, 11];

// The reference unit each product resolves to, as returned by web_read with the
// widget's `uom_id: {name, factor, parent_path, rounding}` specification.
const PRODUCT_REFERENCE_UOM = {
    1: { id: 1, name: "Units", factor: 1, parent_path: "1/", rounding: 0.01 },
    2: { id: 2, name: "Dozen", factor: 12, parent_path: "1/2/", rounding: 0.01 },
};

class UomUom extends models.Model {
    _name = "uom.uom";
    name = fields.Char();
    factor = fields.Float();
    relative_factor = fields.Float();
    rounding = fields.Float();
    parent_path = fields.Char();
    relative_uom_id = fields.Many2one({ relation: "uom.uom" });
    _records = Object.values(UOM_ROWS).map((r) => ({
        id: r.id,
        name: r.display_name,
        factor: r.factor,
        relative_factor: r.relative_factor,
        rounding: 0.01,
        parent_path: r.parent_path,
        relative_uom_id: Array.isArray(r.relative_uom_id)
            ? r.relative_uom_id[0]
            : false,
    }));
}

class ProductProduct extends models.Model {
    _name = "product.product";
    name = fields.Char();
    uom_id = fields.Many2one({ relation: "uom.uom" });
    _records = [
        { id: 1, name: "Widget (Units)", uom_id: 1 },
        { id: 2, name: "Widget (Dozen)", uom_id: 2 },
    ];
}

class SaleLine extends models.Model {
    _name = "sale.line";
    product_id = fields.Many2one({ relation: "product.product" });
    product_uom_qty = fields.Float();
    uom_id = fields.Many2one({ relation: "uom.uom" });
    uom_ids = fields.Many2many({ relation: "uom.uom" });
    _records = [
        { id: 1, product_id: 1, product_uom_qty: 7, uom_id: 2, uom_ids: [] }, // ref = Units
        { id: 2, product_id: 2, product_uom_qty: 7, uom_id: 3, uom_ids: [] }, // ref = Dozen
        { id: 3, product_id: false, product_uom_qty: 7, uom_id: 2, uom_ids: [] }, // no product
    ];
}

defineModels([UomUom, ProductProduct, SaleLine]);

/**
 * Deterministically answer the widget's reference-unit fetch and the two-way
 * (common-root / everything-else) search split, recording every search_read
 * domain so tests can assert how many queries ran and how they were shaped.
 */
function mockUomRpc() {
    const searchDomains = [];
    onRpc("product.product", "web_read", ({ args }) => {
        const id = args[0][0];
        return [{ id, uom_id: PRODUCT_REFERENCE_UOM[id] }];
    });
    onRpc("uom.uom", "search_read", ({ kwargs }) => {
        const domain = kwargs.domain;
        searchDomains.push(domain);
        const usesRootSplit = JSON.stringify(domain).includes("=like");
        const isNegated = domain.includes("!");
        let ids;
        if (!usesRootSplit) {
            ids = [...COMMON_ROOT_IDS, ...OTHER_IDS]; // plain, no reference unit
        } else if (isNegated) {
            ids = OTHER_IDS;
        } else {
            ids = COMMON_ROOT_IDS;
        }
        return ids.map((id) => ({ ...UOM_ROWS[id] })).slice(0, kwargs.limit);
    });
    return searchDomains;
}

const FORM_M2O = /* xml */ `
    <form>
        <field name="product_id"/>
        <field name="product_uom_qty"/>
        <field name="uom_id" widget="many2one_uom"
            options="{'product_field': 'product_id', 'quantity_field': 'product_uom_qty'}"/>
    </form>`;

test("many2one_uom: conversions shown relative to the product's unit", async () => {
    const searchDomains = mockUomRpc();
    await mountView({ type: "form", resModel: "sale.line", resId: 1, arch: FORM_M2O });

    await clickFieldDropdown("uom_id");

    // Compatible units (root "1/") first, then the rest. Labels live in the
    // <span>; conversions in a sibling <div class="text-muted">, so `li span`
    // isolates the unit names.
    expect(queryAllTexts(".dropdown-menu li span")).toEqual([
        "Units",
        "Dozen",
        "Pack of 6",
        "g",
        "kg",
    ]);
    // Conversions only on convertible, non-reference units. qty is 7:
    // Dozen -> 7*12, Pack of 6 -> 7*6, both expressed in their parent (Units).
    expect(queryAllTexts(".dropdown-menu li .text-muted")).toEqual([
        "84 Units",
        "42 Units",
    ]);

    // referenceUnit set -> exactly the common-root query and its negation.
    expect(searchDomains).toHaveLength(2);
    expect(JSON.stringify(searchDomains[0])).toInclude("=like");
    expect(searchDomains[1]).toInclude("!");
});

test("many2one_uom: root unit converts into the product's reference unit", async () => {
    mockUomRpc();
    // Product unit is Dozen: 'Units' (a root) has no parent to show, so it is
    // expressed in Dozen -> 7 * 1/12 = 0.58; 'Pack of 6' still shows 7*6 Units.
    await mountView({ type: "form", resModel: "sale.line", resId: 2, arch: FORM_M2O });

    await clickFieldDropdown("uom_id");

    expect(queryAllTexts(".dropdown-menu li .text-muted")).toEqual([
        "0.58 Dozen",
        "42 Units",
    ]);
});

test("many2one_uom: no product falls back to a plain autocomplete", async () => {
    const searchDomains = mockUomRpc();
    await mountView({ type: "form", resModel: "sale.line", resId: 3, arch: FORM_M2O });

    await clickFieldDropdown("uom_id");

    // No reference unit: every unit is listed, none annotated, single query.
    expect(".dropdown-menu li .text-muted").toHaveCount(0);
    expect(searchDomains).toHaveLength(1);
    expect(JSON.stringify(searchDomains[0])).not.toInclude("=like");
});

test("many2many_uom_tags: reference-relative conversions in the tag autocomplete", async () => {
    mockUomRpc();
    await mountView({
        type: "form",
        resModel: "sale.line",
        resId: 1,
        arch: /* xml */ `
            <form>
                <field name="product_id"/>
                <field name="product_uom_qty"/>
                <field name="uom_ids" widget="many2many_uom_tags"
                    options="{'product_field': 'product_id', 'quantity_field': 'product_uom_qty'}"/>
            </form>`,
    });

    await contains(".o_field_many2many_tags input").click();

    // Same reference-relative annotations as the many2one variant, proving the
    // product/qty getters are wired through the inherited tags template.
    expect(queryAllTexts(".dropdown-menu li .text-muted")).toEqual([
        "84 Units",
        "42 Units",
    ]);
});
