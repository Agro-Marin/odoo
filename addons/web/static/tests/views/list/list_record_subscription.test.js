// @ts-check

import { expect, test } from "@odoo/hoot";
import { queryAllTexts } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import {
    defineModels,
    fields,
    findComponent,
    models,
    mountView,
} from "@web/../tests/web_test_helpers";

class Partner extends models.Model {
    _name = "partner";
    foo = fields.Char();
    _records = [
        { id: 1, foo: "a" },
        { id: 2, foo: "b" },
        { id: 3, foo: "c" },
    ];
}

class User extends models.Model {
    _name = "res.users";
    has_group() {
        return true;
    }
}

defineModels([Partner, User]);

const ARCH = `<list><field name="foo"/></list>`;

test.tags("desktop");
test("an in-place reverse of list.records repaints the rows", async () => {
    const view = await mountView({ type: "list", resModel: "partner", arch: ARCH });
    const renderer = /** @type {any} */ (
        findComponent(view, (component) => Boolean(component?.gridState))
    );
    expect(queryAllTexts(".o_data_row .o_data_cell").join("")).toBe("abc");

    renderer.props.list.records.reverse();
    await animationFrame();
    await animationFrame();

    expect(queryAllTexts(".o_data_row .o_data_cell").join("")).toBe("cba");
});

test.tags("desktop");
test("a same-length splice of list.records repaints the rows", async () => {
    const view = await mountView({ type: "list", resModel: "partner", arch: ARCH });
    const renderer = /** @type {any} */ (
        findComponent(view, (component) => Boolean(component?.gridState))
    );
    const { records } = renderer.props.list;
    const reversed = [...records].reverse();

    records.splice(0, records.length, ...reversed);
    await animationFrame();
    await animationFrame();

    expect(queryAllTexts(".o_data_row .o_data_cell").join("")).toBe("cba");
});
