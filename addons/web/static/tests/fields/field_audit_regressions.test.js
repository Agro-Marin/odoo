// @ts-check

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

test.tags("headless");
test("parseMonetary keeps the closing parenthesis of an =-expression", async () => {
    await makeMockEnv();
    expect(parseMonetary("=(1+2)")).toBe(3);
    expect(parseMonetary("=2*(3+4)")).toBe(14);
    expect(parseMonetary("=((1+2))")).toBe(3);
    expect(parseMonetary("=(1+2)*3")).toBe(9);
    for (const expr of ["=1+2", "=(1+2)", "=2*(3+4)", "=(1+2)*3", "=((1+2))"]) {
        expect(parseMonetary(expr)).toBe(parseFloat(expr));
    }
});

test.tags("headless");
test("parseMonetary reads a DECORATED =-expression as an expression", async () => {
    await makeMockEnv();
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

test("a field going clean does not clear a dirty sibling's mark", async () => {
    await mountView({
        type: "form",
        resModel: "audit.probe",
        resId: 1,
        arch: `<form><field name="name"/><field name="other"/></form>`,
    });
    const [nameInput, otherInput] = queryAll(".o_field_widget input");

    nameInput.value = "dirty text";
    nameInput.dispatchEvent(new InputEvent("input", { bubbles: true }));
    await animationFrame();
    expect(".o_form_dirty").toHaveCount(1);

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

    nameInput.value = "x";
    nameInput.dispatchEvent(new InputEvent("input", { bubbles: true }));
    await animationFrame();
    expect(".o_form_dirty").toHaveCount(0);
});

test("progressbar loads a current_value field the arch does not render", async () => {
    await mountView({
        type: "form",
        resModel: "audit.probe",
        resId: 1,
        arch: `<form><field name="int_field" widget="progressbar" options="{'current_value': 'unlisted_max'}"/></form>`,
    });
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

test("progressbar with a literal max does not bind a second input to its own field", async () => {
    await mountView({
        type: "form",
        resModel: "audit.probe",
        resId: 1,
        arch: `<form><field name="int_field" widget="progressbar" options="{'max_value': 200, 'editable': true}"/></form>`,
    });
    expect(".o_progressbar input").toHaveCount(1);
    expect(".o_progressbar input").toHaveValue("7");
    expect(".o_progressbar_value").toHaveText(/\/\s*200/);
});

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

    const nameInput = queryAll(".o_field_widget[name=name] input")[0];
    nameInput.value = "changed";
    nameInput.dispatchEvent(new Event("change", { bubbles: true }));
    await animationFrame();
    await runAllTimers();
    await animationFrame();

    expect(boxes()[0].checked).toBe(true);
    expect(boxes()[1].checked).toBe(false);
});

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

    expect(add("audit_dep_a", [{ nope: 1 }]).rejected).toBe(true);
    expect(add("audit_dep_b", [{ name: 42 }]).rejected).toBe(true);
    expect(add("audit_dep_c", [{ name: "ok", optional: "yes" }]).rejected).toBe(true);

    expect(
        add("audit_dep_d", [{ name: "write_date", type: "datetime" }]).rejected,
    ).toBe(false);
    expect(
        add("audit_dep_e", [{ name: "f", optional: true, readonly: true }]).rejected,
    ).toBe(false);
    expect(
        add("audit_dep_f", [
            { name: "f", type: "date", readonly: "state != 'draft'", placeholder: "p" },
        ]).rejected,
    ).toBe(false);
    expect(add("audit_dep_g", () => []).rejected).toBe(false);
});

test("fieldDependencies: every registered widget still satisfies the schema", async () => {
    await makeMockEnv();
    const survivors = registry
        .category("fields")
        .getEntries()
        .filter(([, w]) => w.fieldDependencies !== undefined);
    expect(survivors.length).toBeGreaterThan(10);
    for (const name of ["date", "datetime", "daterange", "progressbar", "image"]) {
        expect(registry.category("fields").contains(name)).toBe(true);
    }
});

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

    expect(lookups).toBe(3);
});
