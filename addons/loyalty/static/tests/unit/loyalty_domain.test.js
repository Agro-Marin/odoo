import { expect, test } from "@odoo/hoot";
import { Domain } from "@web/core/domain";
import { evaluateExpr } from "@web/core/py_js/py";

// The card search filters used to compare `expiration_date` against the literal
// string 'today', which reached PostgreSQL unevaluated and was read in the server's
// timezone. They now call `context_today()`, which only exists in the client's Python
// interpreter -- so it is the client that has to be able to evaluate them.
test("the loyalty card search filters resolve a real date client-side", () => {
    const active = evaluateExpr(`[
        '&', ('active', '=', True),
        '&', ('program_id.active', '=', True),
        '|', ('expiration_date', '>=', context_today().strftime('%Y-%m-%d')),
             ('expiration_date', '=', False)
    ]`);
    const inactive = evaluateExpr(`[
        '|', ('active', '=', False),
        '|', ('program_id.active', '=', False),
             ('expiration_date', '<', context_today().strftime('%Y-%m-%d'))
    ]`);

    const today = active[5][2];
    expect(today).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(inactive[4][2]).toBe(today);
    expect(new Domain(active).toString()).toInclude(today);
    expect(new Domain(inactive).toString()).toInclude(today);
});

// Guards `loyalty.reward._get_discount_product_domain`, whose result is serialised
// into `reward_product_domain` and re-evaluated here by the Point of Sale. A
// hierarchical operator compiles to a predicate that is true for every record, so
// stating the reward's product category with `child_of` -- the way `loyalty.rule`
// legitimately does for the server -- would discount the whole catalogue.
test("child_of matches every record client-side; the expanded id list does not", () => {
    expect(new Domain([["categ_id", "child_of", 1]]).contains({ categ_id: 999 })).toBe(
        true,
    );
    expect(new Domain([["categ_id", "parent_of", 1]]).contains({ categ_id: 999 })).toBe(
        true,
    );

    expect(new Domain([["categ_id", "in", [1, 2]]]).contains({ categ_id: 999 })).toBe(
        false,
    );
    expect(new Domain([["categ_id", "in", [1, 2]]]).contains({ categ_id: 2 })).toBe(
        true,
    );
});
