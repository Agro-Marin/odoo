import { expect, test } from "@odoo/hoot";
import { Component, xml } from "@odoo/owl";
import {
    defineModels,
    defineWebModels,
    fields,
    models,
    mountView,
} from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/registry";

class PurchaseOrder extends models.Model {
    _name = "purchase.order";
    name = fields.Char();
    _records = [{ id: 7, name: "P0007" }];
}

defineWebModels();
defineModels([PurchaseOrder]);

let seen = null;

class Probe extends Component {
    static template = xml`<span class="probe"/>`;
    static props = ["*"];
    setup() {
        seen = this.props.record;
    }
}
registry.category("view_widgets").add("audit_id_probe", { component: Probe });

test("record.data.id is absent when the arch does not declare it", async () => {
    seen = null;
    await mountView({
        type: "form",
        resModel: "purchase.order",
        resId: 7,
        arch: `<form><field name="name"/><widget name="audit_id_probe"/></form>`,
    });
    expect(Object.keys(seen.data)).not.toInclude("id");
    expect(seen.data.id).toBe(undefined, {
        message: "getIds() would hand `undefined` to the ORM here",
    });
    expect(seen.resId).toBe(7, { message: "resId is populated regardless" });
});

test("record.data.id resolves only because the arch declares the id field", async () => {
    seen = null;
    await mountView({
        type: "form",
        resModel: "purchase.order",
        resId: 7,
        arch: `<form><field name="id" invisible="1"/><field name="name"/><widget name="audit_id_probe"/></form>`,
    });
    expect(Object.keys(seen.data)).toInclude("id");
    expect(seen.data.id).toBe(7);
    expect(seen.resId).toBe(7);
    expect(seen.data.id).toBe(seen.resId, {
        message: "resId is the equivalent with no arch dependency",
    });
});
