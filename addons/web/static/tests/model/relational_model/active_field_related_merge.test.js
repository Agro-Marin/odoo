// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { Component, xml } from "@odoo/owl";
import {
    defineModels,
    fields,
    models,
    mountView,
    webModels,
} from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/registry";
import {
    completeActiveFields,
    makeActiveField,
    patchActiveFields,
} from "@web/model/relational_model/field_metadata";
import {
    computeRevalidationScope,
    invalidateModifierDependencies,
} from "@web/model/relational_model/record_utils";

/**
 * Merging two descriptions of one field.
 *
 * A field can be described more than once -- named twice in an arch, or named
 * once and also pulled in as another widget's dependency -- and the two
 * descriptions need not agree on whether the field has a `related` sub-schema.
 * `buildActiveFieldFromNode` attaches one to a many2one only when the node
 * carries views, and `addFieldDependencies` attaches one only when the
 * *declared* type is x2many. So a bare description merged with a rich one used
 * to dereference `undefined.activeFields` and take the whole asset bundle with
 * it, in `onWillStart`, naming neither the field nor the view.
 */

const { ResCompany, ResPartner, ResUsers } = webModels;

class Bar extends models.Model {
    _name = "bar";
    name = fields.Char();
    _records = [{ id: 1, name: "B1" }];
}

class Foo extends models.Model {
    _name = "foo";
    foo = fields.Char();
    m2o = fields.Many2one({ relation: "bar" });
    line_ids = fields.One2many({ relation: "bar" });
    _records = [{ id: 1, foo: "yop", m2o: 1, line_ids: [1] }];
}

defineModels([Foo, Bar, ResCompany, ResPartner, ResUsers]);

class Probe extends Component {
    static template = xml`<span/>`;
    static props = ["*"];
}

/** the shape `documents_many2one_avatar` has: a many2one that wants a sub-schema */
registry.category("fields").add("test_m2o_with_related", {
    component: Probe,
    supportedTypes: ["many2one"],
    relatedFields: [{ name: "name", type: "char" }],
});
/** the shape `survey_question_trigger` had: an x2many dependency typed as a scalar */
registry.category("fields").add("test_dep_mistyped", {
    component: Probe,
    fieldDependencies: [{ name: "line_ids", type: "many2one" }],
});
registry.category("fields").add("test_dep_typed", {
    component: Probe,
    fieldDependencies: [{ name: "line_ids", type: "one2many" }],
});

describe("merging descriptions of one field", () => {
    describe.current.tags("headless");

    test("patchActiveFields adopts a sub-schema the target lacks", () => {
        const target = makeActiveField();
        const patch = makeActiveField();
        patch.related = {
            activeFields: { name: makeActiveField() },
            fields: { name: { name: "name", type: "char" } },
        };
        patchActiveFields(target, patch);
        expect(Object.keys(target.related.activeFields)).toEqual(["name"]);
        expect(target.related.fields.name.type).toBe("char");
    });

    test("completeActiveFields adopts a sub-schema the target lacks", () => {
        const activeFields = { m2o: makeActiveField() };
        const extra = { m2o: makeActiveField() };
        extra.m2o.related = {
            activeFields: { name: makeActiveField() },
            fields: { name: { name: "name", type: "char" } },
        };
        completeActiveFields(activeFields, extra);
        expect(Object.keys(activeFields.m2o.related.activeFields)).toEqual(["name"]);
    });
});

describe("arches that describe one field twice", () => {
    describe.current.tags("desktop");

    /** @param {string} arch */
    const mount = (arch) =>
        mountView({ resModel: "foo", type: "form", arch, resId: 1 });

    test("many2one: bare node, then a node whose widget wants a sub-schema", async () => {
        await mount(`<form>
            <field name="m2o"/>
            <field name="m2o" widget="test_m2o_with_related"/>
        </form>`);
        expect(`.o_form_view`).toHaveCount(1);
    });

    test("many2one: the same two in the other order", async () => {
        await mount(`<form>
            <field name="m2o" widget="test_m2o_with_related"/>
            <field name="m2o"/>
        </form>`);
        expect(`.o_form_view`).toHaveCount(1);
    });

    test("a dependency mistypes an x2many, then the real node arrives", async () => {
        await mount(`<form>
            <field name="foo" widget="test_dep_mistyped"/>
            <field name="line_ids"><list><field name="name"/></list></field>
        </form>`);
        expect(`.o_form_view`).toHaveCount(1);
    });

    test("CONTROL: the same dependency, correctly typed", async () => {
        await mount(`<form>
            <field name="foo" widget="test_dep_typed"/>
            <field name="line_ids"><list><field name="name"/></list></field>
        </form>`);
        expect(`.o_form_view`).toHaveCount(1);
    });
});

describe("the modifier dependency graph", () => {
    describe.current.tags("headless");

    test("patchActiveFields retires a graph cached for a map it cannot name", () => {
        const activeFields = {
            a: makeActiveField(),
            b: makeActiveField({ invisible: true }),
        };
        // warm the cache while nothing depends on anything
        expect([...computeRevalidationScope(["a"], activeFields)]).toEqual(["a"]);
        // "True" AND "a" === "a": b now depends on a
        patchActiveFields(activeFields.b, makeActiveField({ invisible: "a" }));
        expect(activeFields.b.invisible).toBe("a");
        expect([...computeRevalidationScope(["a"], activeFields)]).toEqual(["a", "b"]);
    });

    test("a patch that changes no modifier leaves the cache alone", () => {
        const activeFields = { a: makeActiveField(), b: makeActiveField() };
        computeRevalidationScope(["a"], activeFields);
        patchActiveFields(activeFields.b, makeActiveField({ onChange: true }));
        expect(activeFields.b.onChange).toBe(true);
        expect([...computeRevalidationScope(["a"], activeFields)]).toEqual(["a"]);
    });

    test("naming the map still works for callers that hold it", () => {
        const activeFields = { a: makeActiveField(), b: makeActiveField() };
        computeRevalidationScope(["a"], activeFields);
        activeFields.b.invisible = "a";
        invalidateModifierDependencies(activeFields);
        expect([...computeRevalidationScope(["a"], activeFields)]).toEqual(["a", "b"]);
    });
});
