// @ts-check

import { expect, test } from "@odoo/hoot";
import {
    defineModels,
    fields,
    findComponent,
    models,
    mountView,
} from "@web/../tests/web_test_helpers";
import { patch } from "@web/core/utils/patch";
import { MagicColumnWidths } from "@web/views/list/column_width_hook";
import { ListGridState } from "@web/views/list/list_grid_state";
import { ListVirtualization } from "@web/views/list/list_virtualization";

const N = 300;

class Partner extends models.Model {
    _name = "partner";
    name = fields.Char();
    _records = Array.from({ length: N }, (_, i) => ({ id: i + 1, name: `r${i}` }));
}

class User extends models.Model {
    _name = "res.users";
    has_group() {
        return true;
    }
}

defineModels([Partner, User]);

const ARCH = `<list limit="300"><field name="name"/></list>`;

test.tags("desktop");
test("ListVirtualization.refresh is reachable from the prototype", async () => {
    const calls = [];
    patch(ListVirtualization.prototype, {
        refresh() {
            calls.push("refresh");
            return super.refresh();
        },
    });
    const view = await mountView({ type: "list", resModel: "partner", arch: ARCH });
    const renderer = findComponent(view, (c) => Boolean(c?.virt));

    expect(calls.length).toBeGreaterThan(0);
    expect(renderer.virt).toBeInstanceOf(ListVirtualization);
    expect(renderer.virt.isActive).toBe(true);
});

test.tags("desktop");
test("MagicColumnWidths.forceColumnWidths is reachable from the prototype", async () => {
    const calls = [];
    patch(MagicColumnWidths.prototype, {
        forceColumnWidths() {
            calls.push("force");
            return super.forceColumnWidths();
        },
    });
    const view = await mountView({ type: "list", resModel: "partner", arch: ARCH });
    const renderer = findComponent(view, (c) => Boolean(c?.columnWidths));

    expect(calls.length).toBeGreaterThan(0);
    expect(renderer.columnWidths).toBeInstanceOf(MagicColumnWidths);
});

test.tags("desktop");
test("ListGridState.rebuild is reachable from the prototype", async () => {
    const calls = [];
    patch(ListGridState.prototype, {
        rebuild() {
            calls.push("rebuild");
            return super.rebuild();
        },
    });
    await mountView({ type: "list", resModel: "partner", arch: ARCH });
    expect(calls.length).toBeGreaterThan(0);
});
