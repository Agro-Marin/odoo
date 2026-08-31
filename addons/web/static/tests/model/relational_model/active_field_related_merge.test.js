// @ts-check

import { beforeEach, describe, expect, test } from "@odoo/hoot";
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

/**
 * Registered per test, not at module scope.
 *
 * The framework snapshots the registry in a global `beforeEach` and restores it
 * in `afterEach` (tests/_framework/env_test_helpers.js), so anything added at
 * MODULE scope is already present when the first snapshot is taken and is never
 * removed again. These three probe widgets leaked that way into every suite that
 * ran after this file, and `fields/field_registry_contract.test.js` -- which
 * iterates the whole `fields` registry -- then checked them against a contract
 * they were never written to satisfy. Measured: that suite is 7 passed alone and
 * 2 failed when this file is loaded first.
 */
function registerProbeFields() {
    registry.category("fields").add("test_m2o_with_related", {
        component: Probe,
        supportedTypes: ["many2one"],
        relatedFields: [{ name: "name", type: "char" }],
    });
    registry.category("fields").add("test_dep_mistyped", {
        component: Probe,
        fieldDependencies: [{ name: "line_ids", type: "many2one" }],
    });
    registry.category("fields").add("test_dep_typed", {
        component: Probe,
        fieldDependencies: [{ name: "line_ids", type: "one2many" }],
    });
}

beforeEach(registerProbeFields);

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
        expect([...computeRevalidationScope(["a"], activeFields)]).toEqual(["a"]);
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
