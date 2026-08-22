import { beforeEach, expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { getKanbanCounters } from "@web/../tests/_framework/kanban_test_helpers";
import {
    contains,
    defineModels,
    fields,
    models,
    mountView,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { AnimatedNumber } from "@web/views/kanban/animated_number";

class Partner extends models.Model {
    _name = "partner";
    _rec_name = "foo";

    foo = fields.Char();
    int_field = fields.Integer({ aggregator: "sum", sortable: true });
    product_id = fields.Many2one({ relation: "product" });
    category_ids = fields.Many2many({ relation: "category" });

    _records = [
        { id: 1, foo: "yop", int_field: 10, product_id: 3, category_ids: [6] },
        { id: 2, foo: "blip", int_field: 9, product_id: 3, category_ids: [6] },
        { id: 3, foo: "gnap", int_field: 17, product_id: 5, category_ids: [7] },
        { id: 4, foo: "yop", int_field: 5, product_id: 5, category_ids: [7] },
    ];
}

class Product extends models.Model {
    _name = "product";
    name = fields.Char();
    _records = [
        { id: 3, name: "hello" },
        { id: 5, name: "xmo" },
    ];
}

class Category extends models.Model {
    _name = "category";
    name = fields.Char();
    _records = [
        { id: 6, name: "gold" },
        { id: 7, name: "silver" },
    ];
}

class User extends models.Model {
    _name = "res.users";
    has_group() {
        return true;
    }
}

defineModels([Partner, Product, Category, User]);

beforeEach(() => {
    patchWithCleanup(AnimatedNumber, { enableAnimations: false });
});

const ARCH = `
    <kanban>
        <progressbar field="foo" colors='{"yop": "success", "blip": "warning"}' sum_field="int_field"/>
        <templates>
            <t t-name="card"><field name="foo"/></t>
        </templates>
    </kanban>`;

test("progressbar sum_field survives a bar toggle when grouped by many2one", async () => {
    await mountView({
        type: "kanban",
        resModel: "partner",
        arch: ARCH,
        groupBy: ["product_id"],
    });

    expect(".o_kanban_group").toHaveCount(2);
    expect(getKanbanCounters()).toEqual(["19", "22"]);

    await contains(".o_kanban_group:first-child .progress-bar.bg-success").click();
    await animationFrame();
    expect(getKanbanCounters()).toEqual(["10", "22"]);

    await contains(".o_kanban_group:first-child .progress-bar.bg-success").click();
    await animationFrame();
    expect(getKanbanCounters()).toEqual(["19", "22"]);
});

test("progressbar sum_field survives a bar toggle when grouped by many2many", async () => {
    await mountView({
        type: "kanban",
        resModel: "partner",
        arch: ARCH,
        groupBy: ["category_ids"],
    });

    expect(".o_kanban_group").toHaveCount(2);
    expect(getKanbanCounters()).toEqual(["19", "22"]);

    await contains(".o_kanban_group:first-child .progress-bar.bg-success").click();
    await animationFrame();
    expect(getKanbanCounters()).toEqual(["10", "22"]);

    await contains(".o_kanban_group:first-child .progress-bar.bg-success").click();
    await animationFrame();
    expect(getKanbanCounters()).toEqual(["19", "22"]);
});
