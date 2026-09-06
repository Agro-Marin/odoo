// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { parseXML } from "@web/core/utils/dom/xml";
import { PivotArchParser } from "@web/views/pivot/pivot_arch_parser";

describe.current.tags("headless");

const parse = (/** @type {string} */ arch) =>
    new PivotArchParser().parse(parseXML(arch));

test("root attributes", () => {
    const info = parse(
        `<pivot string="Sales" default_order="amount desc" disable_linking="1" display_quantity="True"/>`,
    );
    expect(info.title).toBe("Sales");
    expect(info.defaultOrder).toBe("amount desc");
    expect(info.disableLinking).toBe(true);
    expect(info.displayQuantity).toBe(true);
    expect(parse(`<pivot/>`)).toEqual({
        activeMeasures: [],
        colGroupBys: [],
        defaultOrder: null,
        fieldAttrs: {},
        rowGroupBys: [],
        widgets: {},
    });
});

test("field types, intervals, widgets and measures", () => {
    const info = parse(`
        <pivot>
            <field name="partner_id" type="row"/>
            <field name="date" type="col" interval="month" widget="date"/>
            <field name="amount" type="measure" string="Total"/>
            <field name="qty" operator="sum"/>
            <field name="hidden" invisible="1" string="H"/>
            <field name="tagged" type="row" options="{'a': 1}" foo="bar"/>
        </pivot>`);
    expect(info.rowGroupBys).toEqual(["partner_id", "tagged"]);
    expect(info.colGroupBys).toEqual(["date:month"]);
    expect(info.activeMeasures).toEqual(["amount", "qty"]);
    expect(info.widgets).toEqual({ "date:month": "date" });
    expect(info.fieldAttrs.amount.string).toBe("Total");
    expect(info.fieldAttrs.hidden).toEqual({ string: "H", isInvisible: true });
    expect(info.fieldAttrs.tagged).toEqual({ options: { a: 1 }, foo: "bar" });
});

test("a field without a name is an arch error", () => {
    expect(() => parse(`<pivot><field type="row"/></pivot>`)).toThrow(
        /requires a "name" attribute/,
    );
});
