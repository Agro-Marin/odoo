// @ts-check

/**
 * Regressions for defects found in a field-layer audit. Each test pins one of
 * them; every one of these failed before the accompanying fix.
 */

import { expect, test } from "@odoo/hoot";
import { click, queryAll, queryFirst } from "@odoo/hoot-dom";
import { animationFrame, runAllTimers } from "@odoo/hoot-mock";
import { Component, onMounted, toRaw, xml } from "@odoo/owl";
import {
    defineModels,
    fields,
    makeMockEnv,
    models,
    mountView,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { parseFloat, parseMonetary } from "@web/core/parsers";
import { registry } from "@web/core/registry";
import { GaugeField } from "@web/fields/display/gauge/gauge_field";
import { Field } from "@web/fields/field";
import { standardFieldProps } from "@web/fields/standard_field_props";
import { DateTimeField } from "@web/fields/temporal/datetime/datetime_field";

import { setupChartJsForTests } from "../views/graph/graph_test_helpers.js";

class AuditProbe extends models.Model {
    _name = "audit.probe";
    name = fields.Char();
    other = fields.Char();
    date_field = fields.Date();
    int_field = fields.Integer();
    unlisted_max = fields.Integer();
    state = fields.Selection({
        selection: [
            ["a", "A"],
            ["b", "B"],
        ],
    });
    _records = [
        {
            id: 1,
            name: "x",
            other: "",
            date_field: "2024-01-31",
            int_field: 7,
            unlisted_max: 20,
            state: "a",
        },
    ];
}

class AuditUser extends models.Model {
    _name = "res.users";
    has_group() {
        return true;
    }
}

class JsonProbe extends models.Model {
    _name = "json.probe";
    name = fields.Char();
    flags = fields.Json();
    _records = [
        {
            id: 1,
            name: "a",
            flags: {
                x: { checked: false, string: "X" },
                y: { checked: false, string: "Y" },
            },
        },
    ];
    // an onchange on a NEIGHBOURING field that rewrites the json wholesale
    _onChanges = {
        name(record) {
            record.flags = {
                x: { checked: false, string: "X" },
                y: { checked: false, string: "Y" },
            };
        },
    };
}

defineModels([AuditProbe, JsonProbe, AuditUser]);
setupChartJsForTests();

// ---------------------------------------------------------------------------
// parseMonetary: `=`-expressions are expression syntax, not currency decoration
// ---------------------------------------------------------------------------

test.tags("headless");
test("parseMonetary keeps the closing parenthesis of an =-expression", async () => {
    await makeMockEnv();
    // Each of these ends in ")", which the trailing-decoration strip removed.
    expect(parseMonetary("=(1+2)")).toBe(3);
    expect(parseMonetary("=2*(3+4)")).toBe(14);
    expect(parseMonetary("=((1+2))")).toBe(3);
    // ...and one that never regressed, because it ends in a digit.
    expect(parseMonetary("=(1+2)*3")).toBe(9);
    // monetary must agree with float on every expression form
    for (const expr of ["=1+2", "=(1+2)", "=2*(3+4)", "=(1+2)*3", "=((1+2))"]) {
        expect(parseMonetary(expr)).toBe(parseFloat(expr));
    }
});

test.tags("headless");
test("parseMonetary reads a DECORATED =-expression as an expression", async () => {
    await makeMockEnv();
    // The old guard tested `startsWith("=")` before currency decoration was
    // stripped, so these took the accounting-negative path and came out negated.
    expect(parseMonetary("$ =(1+2)")).toBe(3);
    expect(parseMonetary("$ =1+2")).toBe(3);
});

test.tags("headless");
test("parseMonetary still reads parentheses as an accounting negative", async () => {
    await makeMockEnv();
    expect(parseMonetary("(99)")).toBe(-99);
    expect(parseMonetary("USD (99)")).toBe(-99);
    expect(parseMonetary("99-")).toBe(-99);
});

// ---------------------------------------------------------------------------
// date widget: option values reaching typed props go through exprToBoolean
// ---------------------------------------------------------------------------

test("date widget normalises a string 'numeric' option", async () => {
    const seen = [];
    patchWithCleanup(DateTimeField.prototype, {
        setup() {
            seen.push(this.props.numeric);
            super.setup();
        },
    });
    await mountView({
        type: "form",
        resModel: "audit.probe",
        arch: `<form><field name="date_field" options="{'numeric': '1'}"/></form>`,
    });
    expect(seen[0]).toBe(true);
});

// ---------------------------------------------------------------------------
// gauge: max_field is a field dependency, and a non-numeric bound is not NaN
// ---------------------------------------------------------------------------

const gaugeDataset = () => {
    const datasets = [];
    patchWithCleanup(GaugeField.prototype, {
        setup() {
            super.setup();
            onMounted(() =>
                datasets.push(JSON.stringify(this.chart.config.data.datasets[0].data)),
            );
        },
    });
    return datasets;
};

test("gauge pulls in a max_field the arch does not render", async () => {
    const datasets = gaugeDataset();
    await mountView({
        type: "kanban",
        resModel: "audit.probe",
        arch: `<kanban><templates><t t-name="card">
            <field name="int_field" widget="gauge" options="{'max_field': 'unlisted_max'}"/>
        </t></templates></kanban>`,
    });
    // was "[7,null]": Math.max(7, undefined) === NaN
    expect(datasets[0]).toBe("[7,13]");
});

test("gauge still works when the arch does render the max_field", async () => {
    const datasets = gaugeDataset();
    await mountView({
        type: "kanban",
        resModel: "audit.probe",
        arch: `<kanban><field name="unlisted_max"/><templates><t t-name="card">
            <field name="int_field" widget="gauge" options="{'max_field': 'unlisted_max'}"/>
        </t></templates></kanban>`,
    });
    expect(datasets[0]).toBe("[7,13]");
});

// ---------------------------------------------------------------------------
// copy-to-clipboard wrappers carry the wrapped widget's props
// ---------------------------------------------------------------------------

test("CopyClipboardChar forwards placeholder to the inner CharField", async () => {
    await mountView({
        type: "form",
        resModel: "audit.probe",
        arch: `<form><field name="name" widget="CopyClipboardChar" placeholder="Type here"/></form>`,
    });
    expect(queryFirst(".o_field_widget input").getAttribute("placeholder")).toBe(
        "Type here",
    );
});

test("CopyClipboardChar forwards the password attribute", async () => {
    await mountView({
        type: "form",
        resModel: "audit.probe",
        arch: `<form><field name="name" widget="CopyClipboardChar" password="1"/></form>`,
    });
    expect(queryFirst(".o_field_widget input").getAttribute("type")).toBe("password");
});

// ---------------------------------------------------------------------------
// progressbar honours the required modifier its template reads
// ---------------------------------------------------------------------------

test("progressbar applies the required modifier to its input", async () => {
    await mountView({
        type: "form",
        resModel: "audit.probe",
        arch: `<form><field name="int_field" widget="progressbar" required="1" options="{'editable': true}"/></form>`,
    });
    const inputs = queryAll(".o_progressbar input");
    expect(inputs).toHaveLength(1);
    expect(inputs[0].hasAttribute("required")).toBe(true);
});

// ---------------------------------------------------------------------------
// FIELD_IS_DIRTY is per-field, not last-writer-wins
// ---------------------------------------------------------------------------

test("a field going clean does not clear a dirty sibling's mark", async () => {
    await mountView({
        type: "form",
        resModel: "audit.probe",
        resId: 1,
        arch: `<form><field name="name"/><field name="other"/></form>`,
    });
    const [nameInput, otherInput] = queryAll(".o_field_widget input");

    // Field A holds uncommitted input (no blur, so the record is still clean).
    nameInput.value = "dirty text";
    nameInput.dispatchEvent(new InputEvent("input", { bubbles: true }));
    await animationFrame();
    expect(".o_form_dirty").toHaveCount(1);

    // Field B goes dirty then clean. Its "clean" used to speak for the record.
    otherInput.value = "z";
    otherInput.dispatchEvent(new InputEvent("input", { bubbles: true }));
    await animationFrame();
    expect(".o_form_dirty").toHaveCount(1);
    otherInput.value = "";
    otherInput.dispatchEvent(new InputEvent("input", { bubbles: true }));
    await animationFrame();
    expect(".o_form_dirty").toHaveCount(1);
});

test("the field-level dirty mark drains when the input is restored", async () => {
    // Control for the test above: the aggregate must still be able to reach
    // "clean". Uncommitted input only, so `record.dirty` stays false throughout
    // and `.o_form_dirty` reflects the field signal alone.
    await mountView({
        type: "form",
        resModel: "audit.probe",
        resId: 1,
        arch: `<form><field name="name"/><field name="other"/></form>`,
    });
    const [nameInput] = queryAll(".o_field_widget input");

    nameInput.value = "typed";
    nameInput.dispatchEvent(new InputEvent("input", { bubbles: true }));
    await animationFrame();
    expect(".o_form_dirty").toHaveCount(1);

    nameInput.value = "x"; // the stored value
    nameInput.dispatchEvent(new InputEvent("input", { bubbles: true }));
    await animationFrame();
    expect(".o_form_dirty").toHaveCount(0);
});

// ---------------------------------------------------------------------------
// Options that NAME a same-record field must put that field in the read spec.
// Nothing does this implicitly: `{type: "field"}` in `supportedOptions` is
// Studio metadata, so each such option needs a `fieldDependencies` entry.
// ---------------------------------------------------------------------------

test("progressbar loads a current_value field the arch does not render", async () => {
    await mountView({
        type: "form",
        resModel: "audit.probe",
        resId: 1,
        arch: `<form><field name="int_field" widget="progressbar" options="{'current_value': 'unlisted_max'}"/></form>`,
    });
    // reflects unlisted_max (20), not the fallback 0
    expect(".o_progressbar_value").toHaveText(/^20\s*%$/);
});

test("progressbar still accepts a LITERAL max_value (not a field name)", async () => {
    await mountView({
        type: "form",
        resModel: "audit.probe",
        resId: 1,
        arch: `<form><field name="int_field" widget="progressbar" options="{'max_value': 200}"/></form>`,
    });
    expect(".o_progressbar_value").toHaveText(/^7\s*\/\s*200$/);
});

test("statinfo loads a label_field the arch does not render", async () => {
    await mountView({
        type: "form",
        resModel: "audit.probe",
        resId: 1,
        arch: `<form><field name="int_field" widget="statinfo" options="{'label_field': 'name'}"/></form>`,
    });
    expect(".o_field_widget[name=int_field]").toHaveText(/x/);
});

test("placeholder_field is loaded for any widget that accepts a placeholder", async () => {
    await mountView({
        type: "form",
        resModel: "audit.probe",
        resId: 1,
        arch: `<form><field name="other" options="{'placeholder_field': 'name'}"/></form>`,
    });
    // `name` is "x" on record 1 and is NOT rendered by this arch
    expect(".o_field_widget[name=other] input").toHaveAttribute("placeholder", "x");
});

test("a placeholder_field naming an unknown field does not break the read", async () => {
    await mountView({
        type: "form",
        resModel: "audit.probe",
        resId: 1,
        arch: `<form><field name="other" options="{'placeholder_field': 'no_such_field'}"/></form>`,
    });
    expect(".o_field_widget[name=other] input").toHaveCount(1);
});

// ---------------------------------------------------------------------------
// useInputField is inert when it is not bound to a field
// ---------------------------------------------------------------------------

test("progressbar with a literal max does not bind a second input to its own field", async () => {
    // The max input is not rendered for a literal bound, and the hook that
    // would have driven it must not have re-bound itself to `int_field`.
    await mountView({
        type: "form",
        resModel: "audit.probe",
        resId: 1,
        arch: `<form><field name="int_field" widget="progressbar" options="{'max_value': 200, 'editable': true}"/></form>`,
    });
    // Exactly one input: the current value. A second one would mean the max
    // hook bound itself to a field after all.
    expect(".o_progressbar input").toHaveCount(1);
    expect(".o_progressbar input").toHaveValue("7");
    expect(".o_progressbar_value").toHaveText(/\/\s*200/);
});

// ---------------------------------------------------------------------------
// json_checkboxes: an uncommitted toggle is not clobbered by a model patch
// ---------------------------------------------------------------------------

test("json_checkboxes: a toggle survives an onchange inside the debounce window", async () => {
    await mountView({
        type: "form",
        resModel: "json.probe",
        resId: 1,
        arch: `<form><field name="name"/><field name="flags" widget="json_checkboxes"/></form>`,
    });
    const boxes = () => queryAll(".o_field_widget[name=flags] input[type=checkbox]");
    await click(boxes()[0]);
    await animationFrame();

    // the onchange lands before the 100ms debounce fires
    const nameInput = queryAll(".o_field_widget[name=name] input")[0];
    nameInput.value = "changed";
    nameInput.dispatchEvent(new Event("change", { bubbles: true }));
    await animationFrame();
    await runAllTimers();
    await animationFrame();

    expect(boxes()[0].checked).toBe(true);
    expect(boxes()[1].checked).toBe(false);
});

// ---------------------------------------------------------------------------
// registry: a `fieldDependencies` declaration is actually validated
//
// The schema nested `shape` as a sibling of `element`; owl's validateType
// checks `element` first and returns, so the shape was never applied and any
// malformed entry was accepted. The corrected schema must reject junk while
// still admitting every shape the real widgets declare.
// ---------------------------------------------------------------------------

test("fieldDependencies: a malformed declaration is rejected, valid ones are kept", async () => {
    await makeMockEnv();
    const fieldsReg = registry.category("fields");
    class Probe extends Component {
        static template = xml`<span/>`;
        static props = { ...standardFieldProps };
    }
    const add = (key, fieldDependencies) => {
        let error = null;
        try {
            fieldsReg.add(key, { component: Probe, fieldDependencies });
        } catch (e) {
            error = e;
        }
        return { rejected: Boolean(error) || !fieldsReg.contains(key) };
    };
    patchWithCleanup(odoo, { debug: "1" });

    // rejected: no `name`, and `name` of the wrong type
    expect(add("audit_dep_a", [{ nope: 1 }]).rejected).toBe(true);
    expect(add("audit_dep_b", [{ name: 42 }]).rejected).toBe(true);
    expect(add("audit_dep_c", [{ name: "ok", optional: "yes" }]).rejected).toBe(true);

    // accepted: every form the shipped widgets actually declare
    expect(
        add("audit_dep_d", [{ name: "write_date", type: "datetime" }]).rejected,
    ).toBe(false);
    expect(
        add("audit_dep_e", [{ name: "f", optional: true, readonly: true }]).rejected,
    ).toBe(false);
    // daterange spreads the node's arch attrs, so `readonly` arrives as a py expr
    expect(
        add("audit_dep_f", [
            { name: "f", type: "date", readonly: "state != 'draft'", placeholder: "p" },
        ]).rejected,
    ).toBe(false);
    expect(add("audit_dep_g", () => []).rejected).toBe(false);
});

test("fieldDependencies: every registered widget still satisfies the schema", async () => {
    await makeMockEnv();
    // A widget dropped by validation is silently removed outside debug mode,
    // which would blank the field. Nothing may be missing from the registry.
    const survivors = registry
        .category("fields")
        .getEntries()
        .filter(([, w]) => w.fieldDependencies !== undefined);
    expect(survivors.length).toBeGreaterThan(10);
    for (const name of ["date", "datetime", "daterange", "progressbar", "image"]) {
        expect(registry.category("fields").contains(name)).toBe(true);
    }
});

// ---------------------------------------------------------------------------
// Field: a modifier expression is evaluated once per render, not three times
// ---------------------------------------------------------------------------

test("Field evaluates readonly/required once per render", async () => {
    let lookups = 0;
    class Probe extends models.Model {
        _name = "eval.probe";
        name = fields.Char();
        gate = fields.Char();
        _records = [{ id: 1, name: "n", gate: "on" }];
    }
    defineModels([Probe]);

    patchWithCleanup(Field.prototype, {
        setup() {
            const raw = toRaw(this.props.record);
            if (!raw.__auditProbed) {
                raw.__auditProbed = true;
                const real = raw.evalContextWithVirtualIds;
                Object.defineProperty(raw, "evalContextWithVirtualIds", {
                    configurable: true,
                    writable: true,
                    // one py evaluation copies the context once, reading each name
                    value: new Proxy(real, {
                        get(target, prop, receiver) {
                            if (prop === "gate") {
                                lookups++;
                            }
                            return Reflect.get(target, prop, receiver);
                        },
                    }),
                });
            }
            return super.setup();
        },
    });

    await mountView({
        type: "form",
        resModel: "eval.probe",
        resId: 1,
        arch: `<form><group>
                 <field name="gate" invisible="1"/>
                 <field name="name" readonly="gate == 'on'" required="gate != 'off'"/>
               </group></form>`,
    });

    // readonly + required, once each: Field.classNames and
    // Field.fieldComponentProps share one computation, and FormLabel never
    // touches `required`.
    expect(lookups).toBe(3);
});
