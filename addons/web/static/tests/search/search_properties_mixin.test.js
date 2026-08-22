// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { Component, xml } from "@odoo/owl";
import {
    defineModels,
    fields,
    models,
    mountWithSearch,
} from "@web/../tests/web_test_helpers";

describe.current.tags("headless");

class TestComponent extends Component {
    static template = xml`<div class="o_test_component"/>`;
    static props = ["*"];
}

class Foo extends models.Model {
    name = fields.Char();
    foo = fields.Char();
    bar = fields.Many2one({ relation: "partner" });
    properties = fields.Properties({
        definition_record: "bar",
        definition_record_field: "child_properties",
    });
    other_props = fields.Properties({
        definition_record: "bar",
        definition_record_field: "child_properties",
    });
    _records = [];
}

class Partner extends models.Model {
    name = fields.Char();
    child_properties = fields.PropertiesDefinition();
    _records = [];
}

defineModels([Foo, Partner]);

const ARCH = `
    <search>
        <field name="properties"/>
        <field name="other_props"/>
    </search>
`;

async function createSearchModel() {
    const component = await mountWithSearch(TestComponent, {
        resModel: "foo",
        searchViewId: false,
        searchViewArch: ARCH,
    });
    return component.env.searchModel;
}

function stubDefinitions(model, getDefinitions) {
    model._fetchPropertiesDefinition = async (_resModel, fieldName) => [
        {
            definitionRecordId: 1,
            definitionRecordName: "Parent",
            definitions: getDefinitions()[fieldName],
        },
    ];
}

async function activateAllPropertyGroupBys(model) {
    for (const item of model.getSearchItems((i) => i.isProperty)) {
        await model.toggleSearchItem(item.id);
    }
}

test("retiring one properties field leaves the other field's group-bys alone", async () => {
    const model = await createSearchModel();
    let definitions = {
        properties: [{ name: "p1", string: "P1", type: "char" }],
        other_props: [{ name: "q1", string: "Q1", type: "char" }],
    };
    stubDefinitions(model, () => definitions);

    await model.fillSearchViewItemsProperty();
    await activateAllPropertyGroupBys(model);
    expect(model.groupBy).toEqual(["properties.p1", "other_props.q1"]);

    definitions = { properties: [], other_props: definitions.other_props };
    await model.fillSearchViewItemsProperty();

    expect(model.groupBy).toEqual(["other_props.q1"]);
});

test("overlapping fills that both retire everything still settle", async () => {
    const model = await createSearchModel();
    let definitions = {
        properties: [{ name: "p1", string: "P1", type: "char" }],
        other_props: [{ name: "q1", string: "Q1", type: "char" }],
    };
    stubDefinitions(model, () => definitions);

    await model.fillSearchViewItemsProperty();
    await activateAllPropertyGroupBys(model);
    expect(model.groupBy).toHaveLength(2);

    definitions = { properties: [], other_props: [] };
    await Promise.all([
        model.fillSearchViewItemsProperty(),
        model.fillSearchViewItemsProperty(),
    ]);

    expect(model.groupBy).toEqual([]);
    expect(model.query).toEqual([]);
});

test("retiring a property also retires its synthesised field metadata", async () => {
    const model = await createSearchModel();
    let definitions = {
        properties: [{ name: "p1", string: "P1", type: "char" }],
        other_props: [{ name: "q1", string: "Q1", type: "char" }],
    };
    stubDefinitions(model, () => definitions);

    await model.fillSearchViewItemsProperty();
    expect(model.searchViewFields["properties.p1"]).not.toBe(undefined);
    expect(model.searchViewFields["other_props.q1"]).not.toBe(undefined);

    definitions = { properties: [], other_props: definitions.other_props };
    await model.fillSearchViewItemsProperty();

    expect(model.searchViewFields["properties.p1"]).toBe(undefined);
    expect(model.searchViewFields["other_props.q1"]).not.toBe(undefined);
});

test("a failing definitions fetch retires nothing", async () => {
    const model = await createSearchModel();
    const definitions = {
        properties: [{ name: "p1", string: "P1", type: "char" }],
        other_props: [],
    };
    stubDefinitions(model, () => definitions);

    await model.fillSearchViewItemsProperty();
    await activateAllPropertyGroupBys(model);
    expect(model.groupBy).toEqual(["properties.p1"]);

    model._fetchPropertiesDefinition = async () => {
        throw new Error("rpc down");
    };
    await model.fillSearchViewItemsProperty().catch(() => {});

    expect(model.groupBy).toEqual(["properties.p1"]);
});
