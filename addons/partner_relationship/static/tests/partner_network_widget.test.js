import { expect, test } from "@odoo/hoot";
import { click, queryAll } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup, onRpc } from "@web/../tests/web_test_helpers";
import { PartnerNetwork } from "@partner_relationship/partner_network_widget";

function payload() {
    return {
        focus_id: 1,
        max_degree: 3,
        reached_degree: 2,
        categories: [
            { key: "blood", label: "Consanguinity" },
            { key: "business", label: "Business" },
        ],
        nodes: [
            { id: 1, name: "Juan", degree: 0, is_company: false },
            { id: 2, name: "Maria", degree: 1, is_company: false },
            { id: 3, name: "Pedro", degree: 1, is_company: false },
            { id: 4, name: "Lucia", degree: 2, is_company: false },
        ],
        edges: [
            {
                id: 10,
                source: 1,
                target: 2,
                label: "brother of",
                category: "blood",
                weight_risk: 0.8,
                symmetric: true,
            },
            {
                id: 11,
                source: 1,
                target: 3,
                label: "business partner of",
                category: "business",
                weight_risk: 0.9,
                symmetric: true,
            },
            {
                id: 12,
                source: 3,
                target: 4,
                label: "sister of",
                category: "blood",
                weight_risk: 0.8,
                symmetric: true,
            },
        ],
    };
}

async function mountNetwork() {
    onRpc("res.partner", "get_relation_network", () => payload());
    await mountWithCleanup(PartnerNetwork, { props: { record: { resId: 1 } } });
    await animationFrame();
    await animationFrame();
}

test("toggling a category redraws once, not on top of the previous paper", async () => {
    await mountNetwork();
    expect(".o_partner_network_canvas svg").toHaveCount(1);
    expect(".o_partner_network_node").toHaveCount(4);

    await click(
        ".o_partner_network_legend_item:has(.o_partner_network_category_blood) input",
    );
    await animationFrame();
    await animationFrame();

    expect(".o_partner_network_canvas svg").toHaveCount(1);
    expect(".o_partner_network_node").toHaveCount(2);
    expect(queryAll(".o_partner_network_paper > *")).toHaveLength(1);
});

test("hiding every category and restoring it draws the whole network once", async () => {
    await mountNetwork();

    await click(".o_partner_network_legend .btn:contains(None)");
    await animationFrame();
    await animationFrame();
    expect(".o_partner_network_node").toHaveCount(1);

    await click(".o_partner_network_legend .btn:contains(All)");
    await animationFrame();
    await animationFrame();
    expect(".o_partner_network_canvas svg").toHaveCount(1);
    expect(".o_partner_network_node").toHaveCount(4);
});

test("moving the focus to a clicked contact reloads its network", async () => {
    let calls = 0;
    onRpc("res.partner", "get_relation_network", ({ args }) => {
        calls += 1;
        return { ...payload(), focus_id: args[0][0] };
    });
    await mountWithCleanup(PartnerNetwork, { props: { record: { resId: 1 } } });
    await animationFrame();
    await animationFrame();
    expect(calls).toBe(1);

    await click(
        ".o_partner_network_legend_item:has(.o_partner_network_category_blood) input",
    );
    await animationFrame();
    expect(calls).toBe(1);
    expect(".o_partner_network_toolbar .fa-undo").toHaveCount(0);
});
