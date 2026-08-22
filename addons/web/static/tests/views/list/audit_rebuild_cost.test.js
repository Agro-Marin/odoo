import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import {
    contains,
    defineModels,
    fields,
    models,
    mountView,
} from "@web/../tests/web_test_helpers";
import { findComponent } from "@web/../tests/web_test_helpers";
import { patch } from "@web/core/utils/patch";
import { ListGridState } from "@web/views/list/list_grid_state";

const N_RECORDS = 400;

class Partner extends models.Model {
    _name = "partner";
    foo = fields.Char();
    int_field = fields.Integer();
    _records = Array.from({ length: N_RECORDS }, (_, i) => ({
        id: i + 1,
        foo: `rec${i}`,
        int_field: i,
    }));
}

class User extends models.Model {
    _name = "res.users";
    has_group() {
        return true;
    }
}

defineModels([Partner, User]);

function instrumentRebuild() {
    const stats = { rebuilds: 0, rowsMaterialized: 0 };
    const stop = patch(ListGridState.prototype, {
        rebuild() {
            stats.rebuilds++;
            const result = super.rebuild();
            stats.rowsMaterialized += /** @type {any} */ (this).rowCount;
            return result;
        },
    });
    return { stats, stop };
}

const ARCH = `<list editable="bottom" limit="400"><field name="foo"/><field name="int_field"/></list>`;

test("one cell click re-materializes the whole loaded record set", async () => {
    await mountView({ type: "list", resModel: "partner", arch: ARCH });

    const domRowsBefore = document.querySelectorAll(".o_data_row").length;
    const { stats, stop } = instrumentRebuild();

    await contains(".o_data_row:first-child .o_data_cell").click();
    await animationFrame();

    stop();

    expect(stats.rebuilds).toBeGreaterThan(0, {
        message: "control: rebuild really ran during the interaction",
    });
    expect(stats.rowsMaterialized / stats.rebuilds).toBe(N_RECORDS, {
        message: "each rebuild walks all loaded records, not just the visible window",
    });
    expect(domRowsBefore).toBeLessThan(N_RECORDS, {
        message: "control: virtualization really is limiting the DOM",
    });
});

test("typing in an edited cell does NOT re-render the renderer", async () => {
    await mountView({ type: "list", resModel: "partner", arch: ARCH });
    await contains(".o_data_row:first-child .o_data_cell").click();
    await animationFrame();

    const { stats, stop } = instrumentRebuild();
    await contains(".o_data_row:first-child .o_data_cell input").edit("abcde", {
        confirm: false,
    });
    await animationFrame();
    stop();

    expect(stats.rebuilds).toBe(0, {
        message: "no gridState.rebuild() at all while typing",
    });
});

test("an unchanged rebuild reuses every row object", async () => {
    const view = await mountView({ type: "list", resModel: "partner", arch: ARCH });

    const gridState = /** @type {any} */ (
        findComponent(view, (c) => Boolean(c?.gridState))
    ).gridState;

    const rowsBefore = gridState.flatRows.slice();

    gridState.rebuild();

    expect(
        gridState.flatRows.every(
            (/** @type {any} */ row, /** @type {any} */ i) => row === rowsBefore[i],
        ),
    ).toBe(true, {
        message: "every FlatRow object is reused, not reallocated",
    });
});
