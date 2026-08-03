// @ts-check

/**
 * `web.Field` mounts every widget with `t-props="fieldComponentProps"`, and
 * that getter rebuilds two values on every render: the `context` object (fresh
 * out of `getFieldContext`) and the `domain` closure. Under a dynamic prop list
 * OWL compares *every* prop by identity, so those two are enough to re-render
 * the whole widget subtree on any record change, however unrelated.
 *
 * This test pins that cost -- and, more importantly, exists to stop the next
 * reader from "fixing" it the obvious way. Memoising `context` by value and
 * hoisting `domain` to a single bound method makes the numbers below go to
 * zero, and breaks 14 tests, because the churn is load-bearing:
 *
 *  - `useActiveActions` recomputes `create`/`delete` domains only in
 *    `onWillUpdateProps`, so conditional actions freeze at their first value.
 *  - `useSpecialData`'s second loader is also an `onWillUpdateProps`, so a
 *    statusbar or checkbox set with a dynamic domain stops reloading.
 *  - `PropertyValue` reformats its input on re-render, so a property whose type
 *    changes keeps rendering the old format ("0" where "0.00" is due).
 *
 * Hoisting `domain` is worse than it looks: reading `this.props.record` from a
 * method on `Field` evaluates the domain through the *Field's* reactive proxy,
 * so a widget's own `useRecordObserver` never subscribes to what the domain
 * depends on. A real fix has to give those three consumers a dependency on the
 * record rather than on how often props are rebuilt; it is not a memoisation.
 */

import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import {
    contains,
    defineModels,
    fields,
    models,
    mountView,
} from "@web/../tests/web_test_helpers";

class Tag extends models.Model {
    _name = "tag";
    name = fields.Char();
    _records = [{ id: 1, name: "t1" }];
}

class Partner extends models.Model {
    name = fields.Char();
    other = fields.Char();
    tag_ids = fields.Many2many({ relation: "tag" });
    _records = [{ id: 1, name: "p", other: "o", tag_ids: [1] }];
}

class ResUsers extends models.Model {
    _name = "res.users";
    has_group() {
        return true;
    }
}

defineModels([Partner, Tag, ResUsers]);

/**
 * @param {() => Promise<void>} workload
 * @returns {Promise<Record<string, number>>}
 */
async function renderCounts(workload) {
    const g = /** @type {any} */ (globalThis);
    g.__renderTrace = true;
    g.__renderReset();
    try {
        await workload();
    } finally {
        g.__renderTrace = false;
    }
    return g.__renderStats();
}

test("a widget re-renders once per unrelated committed edit", async () => {
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <field name="name"/>
                <field name="other"/>
                <field name="tag_ids" widget="many2many_tags"/>
            </form>`,
    });
    await animationFrame();

    const stats = await renderCounts(async () => {
        for (const value of ["x", "xy", "xyz", "xyza", "xyzab"]) {
            await contains("[name='name'] input").edit(value);
            await animationFrame();
        }
    });

    // The edited field, once per committed edit -- that part is necessary.
    expect(stats["fields.CharField"]).toBe(5);
    // The tags widget, same count, for a record change it does not read. This
    // is the cost; see the module comment before trying to drive it to 0.
    expect(stats["fields.Many2ManyTagsField"]).toBe(5);
});
