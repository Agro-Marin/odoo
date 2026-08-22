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

/**
 * `ListGridState._materialize` walks `toRaw(list.records)` and reads the reactive
 * `records[i]` only for a row it has to rebuild, which is what took its cost on
 * 4000 rows from 4.23ms to 0.147ms. It therefore no longer registers a
 * subscription on every index key of the array.
 *
 * Those subscriptions still exist, from `useListAggregates.getAggregationValues`,
 * which does `list.records.map(...)` and is reached from the unconditional
 * `<tfoot><ListAggregatesRow/>`. Both mutations below are ones the model really
 * performs in place with no change of length - `resequence.js` reverses and
 * splices, `static_list._applyServerValues` assigns an index - so if that walk
 * ever stops being reactive, these fail and name the coupling.
 */
test.tags("desktop");
test("an in-place reverse of list.records repaints the rows", async () => {
    const view = await mountView({ type: "list", resModel: "partner", arch: ARCH });
    const renderer = findComponent(view, (component) => Boolean(component?.gridState));
    expect(queryAllTexts(".o_data_row .o_data_cell").join("")).toBe("abc");

    renderer.props.list.records.reverse();
    await animationFrame();
    await animationFrame();

    expect(queryAllTexts(".o_data_row .o_data_cell").join("")).toBe("cba");
});

test.tags("desktop");
test("a same-length splice of list.records repaints the rows", async () => {
    const view = await mountView({ type: "list", resModel: "partner", arch: ARCH });
    const renderer = findComponent(view, (component) => Boolean(component?.gridState));
    const { records } = renderer.props.list;
    const reversed = [...records].reverse();

    records.splice(0, records.length, ...reversed);
    await animationFrame();
    await animationFrame();

    expect(queryAllTexts(".o_data_row .o_data_cell").join("")).toBe("cba");
});
