// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { Component, xml } from "@odoo/owl";
import { parseXML } from "@web/core/utils/dom/xml";
import { registerField } from "@web/fields/_registry";
import { charField } from "@web/fields/basic/char/char_field";
import { ListArchParser } from "@web/views/list/list_arch_parser";

describe.current.tags("headless");

const MODELS = {
    foo: {
        fields: {
            id: { type: "integer", string: "ID" },
            name: { type: "char", string: "Name" },
            partner_id: { type: "many2one", string: "Partner", relation: "partner" },
        },
    },
    partner: {
        fields: {
            id: { type: "integer", string: "ID" },
            display_name: { type: "char", string: "Display name" },
        },
    },
};

class ScopedChar extends Component {
    static template = xml`<span/>`;
    static props = ["*"];
}
const scopedCharField = { ...charField, component: ScopedChar };

test("js_class scopes the field lookup of every column", () => {
    registerField({ name: "char", view: "scoped_list" }, scopedCharField);
    const parse = (/** @type {string} */ arch) =>
        new ListArchParser().parse(parseXML(arch), MODELS, "foo");

    const plain = parse(`<list><field name="name"/></list>`);
    expect(plain.fieldNodes.name_0.field).toBe(charField);

    const scoped = parse(`<list js_class="scoped_list"><field name="name"/></list>`);
    expect(scoped.fieldNodes.name_0.field).toBe(scopedCharField);
    expect(scoped.columns[0].field).toBe(scopedCharField);
});

test("js_class reaches the fields of a groupby sub-arch", () => {
    registerField({ name: "char", view: "scoped_list" }, scopedCharField);
    const archInfo = new ListArchParser().parse(
        parseXML(`
            <list js_class="scoped_list">
                <field name="name"/>
                <groupby name="partner_id">
                    <field name="display_name"/>
                </groupby>
            </list>`),
        MODELS,
        "foo",
    );
    const groupFieldNodes = archInfo.groupBy.fields.partner_id.fieldNodes;
    expect(groupFieldNodes.display_name_0.field).toBe(scopedCharField);
});
