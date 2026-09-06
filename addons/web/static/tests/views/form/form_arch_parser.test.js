// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { parseXML } from "@web/core/utils/dom/xml";
import { FormArchParser } from "@web/views/form/form_arch_parser";

describe.current.tags("headless");

const MODELS = {
    partner: {
        fields: {
            id: { type: "integer", string: "ID" },
            name: { type: "char", string: "Name" },
            email: { type: "char", string: "Email" },
            props: { type: "properties", string: "Properties" },
        },
    },
};

const parse = (/** @type {string} */ arch) =>
    new FormArchParser().parse(parseXML(arch), MODELS, "partner");

test("active actions and autofocus", () => {
    const info = parse(`
        <form create="0" disable_autofocus="1">
            <field name="name" default_focus="1"/>
            <field name="email"/>
            <field name="name"/>
        </form>`);
    expect(info.activeActions).toEqual({
        type: "view",
        create: false,
        edit: true,
        delete: true,
        duplicate: false,
    });
    expect(info.disableAutofocus).toBe(true);
    expect(info.autofocusFieldIds).toEqual(["name_0"]);
    expect(Object.keys(info.fieldNodes)).toEqual(["name_0", "email_0", "name_1"]);
    expect(info.xmlDoc.querySelectorAll("field[field_id]")).toHaveLength(3);
});

test("a properties field enables the add-property action, a widget node is numbered", () => {
    const info = parse(`
        <form>
            <field name="props"/>
            <widget name="week_days"/>
            <widget name="week_days"/>
        </form>`);
    expect(info.activeActions.addPropertyFieldValue).toBe(true);
    expect(Object.keys(info.widgetNodes)).toEqual(["widget_1", "widget_2"]);
    expect(info.xmlDoc.querySelector("widget")?.getAttribute("widget_id")).toBe(
        "widget_1",
    );
});
