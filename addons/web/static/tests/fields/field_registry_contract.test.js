// @ts-check

import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import {
    defineModels,
    fields,
    models,
    mountView,
} from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/registry";

class Sub extends models.Model {
    _name = "sub";
    name = fields.Char();
    _records = [{ id: 1, name: "s1" }];
}

class Partner extends models.Model {
    _name = "partner";
    name = fields.Char();
    f_char = fields.Char();
    f_text = fields.Text();
    f_html = fields.Html();
    f_integer = fields.Integer();
    f_float = fields.Float();
    f_monetary = fields.Monetary({ currency_field: "currency_id" });
    currency_id = fields.Many2one({ relation: "res.currency" });
    f_boolean = fields.Boolean();
    f_date = fields.Date();
    f_datetime = fields.Datetime();
    f_selection = fields.Selection({
        selection: [
            ["a", "A"],
            ["b", "B"],
        ],
    });
    f_many2one = fields.Many2one({ relation: "sub" });
    f_one2many = fields.One2many({ relation: "sub", relation_field: "name" });
    f_many2many = fields.Many2many({ relation: "sub" });
    f_binary = fields.Binary();
    f_json = fields.Json();
    write_date = fields.Datetime();

    _records = [
        {
            id: 1,
            name: "p",
            f_char: "c",
            f_text: "t",
            f_html: "<p>h</p>",
            f_integer: 1,
            f_float: 1.5,
            f_monetary: 1.5,
            currency_id: 1,
            f_boolean: true,
            f_date: "2026-01-01",
            f_datetime: "2026-01-01 10:00:00",
            f_selection: "a",
            f_many2one: 1,
            f_one2many: [1],
            f_many2many: [1],
            f_binary: false,
            f_json: false,
            write_date: "2026-01-01 10:00:00",
        },
    ];
    _views = {
        form: `<form><field name="name"/></form>`,
        list: `<list><field name="name"/></list>`,
        search: `<search/>`,
    };
}

class Currency extends models.Model {
    _name = "res.currency";
    name = fields.Char();
    symbol = fields.Char();
    position = fields.Selection({
        selection: [
            ["before", "Before"],
            ["after", "After"],
        ],
    });
    _records = [{ id: 1, name: "USD", symbol: "$", position: "before" }];
}

class ResUsers extends models.Model {
    _name = "res.users";
    has_group() {
        return true;
    }
}

defineModels([Partner, Sub, Currency, ResUsers]);

/** @type {Record<string, string>} */
const FIELD_OF_TYPE = {
    binary: "f_binary",
    boolean: "f_boolean",
    char: "f_char",
    date: "f_date",
    datetime: "f_datetime",
    float: "f_float",
    html: "f_html",
    integer: "f_integer",
    json: "f_json",
    many2many: "f_many2many",
    many2one: "f_many2one",
    monetary: "f_monetary",
    one2many: "f_one2many",
    selection: "f_selection",
    text: "f_text",
};

/**
 * @returns {{ key: string, descr: any, viewType: string, widget: string }[]}
 */
function registryEntries() {
    return registry
        .category("fields")
        .getEntries()
        .map(([key, descr]) => {
            const [prefix, widget] = key.includes(".") ? key.split(".") : ["form", key];
            return { key, descr, viewType: prefix, widget };
        });
}

function mountableEntries() {
    return registryEntries().filter(({ viewType }) =>
        ["form", "list", "kanban"].includes(viewType),
    );
}

/**
 * @param {string} viewType
 * @param {string} fieldName
 * @param {string} widget
 * @returns {string}
 */
function archFor(viewType, fieldName, widget) {
    switch (viewType) {
        case "list":
            return `<list>
                        <field name="currency_id" column_invisible="1"/>
                        <field name="${fieldName}" widget="${widget}"/>
                    </list>`;
        case "kanban":
            return `<kanban><templates><t t-name="card">
                        <field name="currency_id" invisible="1"/>
                        <field name="${fieldName}" widget="${widget}"/>
                    </t></templates></kanban>`;
        default:
            return `<form>
                        <field name="currency_id" invisible="1"/>
                        <field name="${fieldName}" widget="${widget}"/>
                    </form>`;
    }
}

test("every widget renders each type it claims in supportedTypes", async () => {
    const failures = [];
    let attempted = 0;

    for (const { key, descr, viewType, widget } of mountableEntries()) {
        for (const type of descr.supportedTypes || []) {
            const fieldName = FIELD_OF_TYPE[type];
            if (!fieldName) {
                continue;
            }
            attempted++;
            try {
                await mountView({
                    type: /** @type {any} */ (viewType),
                    resModel: "partner",
                    resId: viewType === "form" ? 1 : undefined,
                    arch: archFor(viewType, fieldName, widget),
                });
                await animationFrame();
            } catch (error) {
                failures.push(`${key} / ${type}: ${String(error).slice(0, 160)}`);
            }
        }
    }

    expect(failures).toEqual([]);
    expect(attempted).toBeGreaterThan(100);
});

/**
 * @type {Record<string, string[]>}
 */
const UNDECLARED_BY_DESIGN = {
    date: ["always_range", "end_date_field", "rounding", "start_date_field"],
    datetime: ["always_range", "end_date_field", "start_date_field"],
};

/**
 * @param {any} descr
 * @param {any} value
 * @returns {{ options: Set<string>, attrs: Set<string> } | null}
 */
function namesReadByExtractProps(descr, value) {
    const options = new Set();
    const attrs = new Set();
    const proxyInto = (/** @type {Set<string>} */ sink) =>
        new Proxy(
            {},
            {
                get: (_target, prop) => {
                    if (typeof prop !== "string") {
                        return undefined;
                    }
                    sink.add(prop);
                    return value;
                },
                has: (_target, prop) => {
                    if (typeof prop === "string") {
                        sink.add(prop);
                    }
                    return Boolean(value);
                },
            },
        );
    try {
        descr.extractProps(
            /** @type {any} */ ({
                attrs: proxyInto(attrs),
                options: proxyInto(options),
                string: "",
                placeholder: "",
                decorations: {},
                viewType: "form",
                type: "char",
                name: "f_char",
                views: {},
                relatedFields: {},
            }),
            /** @type {any} */ ({
                context: {},
                domain: () => /** @type {any[]} */ ([]),
                readonly: false,
                required: false,
            }),
        );
    } catch {
        return null;
    }
    return { options, attrs };
}

test("extractProps reads no option that supportedOptions does not declare", () => {
    const drift = [];
    let checked = 0;

    for (const { key, descr, widget } of registryEntries()) {
        if (typeof descr.extractProps !== "function") {
            continue;
        }
        const read = namesReadByExtractProps(descr, undefined);
        if (!read) {
            continue;
        }
        checked++;
        const declared = new Set([
            ...(descr.supportedOptions || []).map((/** @type {any} */ o) => o.name),
            ...(UNDECLARED_BY_DESIGN[widget] || []),
        ]);
        const undeclared = [...read.options]
            .filter((name) => !declared.has(name))
            .sort();
        if (undeclared.length) {
            drift.push(`${key}: ${undeclared.join(", ")}`);
        }
    }

    expect(drift).toEqual([]);
    expect(checked).toBeGreaterThan(88);
});

/**
 * @type {Record<string, string[]>}
 */
const UNDECLARED_ATTRS_BY_DESIGN = {
    boolean_favorite: ["nolabel"],
    statinfo: ["nolabel"],
};

test("extractProps reads no attribute that supportedAttributes does not declare", () => {
    const drift = [];
    let checked = 0;

    for (const { key, descr, widget } of registryEntries()) {
        if (typeof descr.extractProps !== "function") {
            continue;
        }
        const falsy = namesReadByExtractProps(descr, undefined);
        const truthy = namesReadByExtractProps(descr, "1");
        if (!falsy || !truthy) {
            continue;
        }
        checked++;
        const declared = new Set([
            ...(descr.supportedAttributes || []).map((/** @type {any} */ a) => a.name),
            ...(UNDECLARED_ATTRS_BY_DESIGN[widget] || []),
        ]);
        const undeclared = [...new Set([...falsy.attrs, ...truthy.attrs])]
            .filter((name) => !declared.has(name))
            .sort();
        if (undeclared.length) {
            drift.push(`${key}: ${undeclared.join(", ")}`);
        }
    }

    expect(drift).toEqual([]);
    expect(checked).toBeGreaterThan(88);
});

test("supportedOptions and supportedAttributes declare nothing extractProps ignores", () => {
    const drift = [];
    let checked = 0;

    for (const { key, descr } of registryEntries()) {
        if (typeof descr.extractProps !== "function") {
            continue;
        }
        const falsy = namesReadByExtractProps(descr, undefined);
        const truthy = namesReadByExtractProps(descr, "1");
        if (!falsy || !truthy) {
            continue;
        }
        checked++;
        const isRead = (
            /** @type {"options"|"attrs"} */ sink,
            /** @type {string} */ name,
        ) => falsy[sink].has(name) || truthy[sink].has(name);
        const deadOptions = (descr.supportedOptions || [])
            .map((/** @type {any} */ o) => o.name)
            .filter(
                (/** @type {string} */ n) =>
                    n !== "placeholder_field" && !isRead("options", n),
            );
        const deadAttrs = (descr.supportedAttributes || [])
            .map((/** @type {any} */ o) => o.name)
            .filter((/** @type {string} */ n) => !isRead("attrs", n));
        if (deadOptions.length || deadAttrs.length) {
            drift.push(
                `${key}: options[${deadOptions.join(", ")}] attributes[${deadAttrs.join(", ")}]`,
            );
        }
    }

    expect(drift).toEqual([]);
    expect(checked).toBeGreaterThan(88);
});

/**
 * @type {string[]}
 */
const NUMERIC_TYPES = ["integer", "float", "monetary"];

test("every numeric widget opts out of the falsy-is-empty default", () => {
    const missing = registryEntries()
        .filter(
            ({ descr }) =>
                (descr.supportedTypes || []).some((/** @type {string} */ t) =>
                    NUMERIC_TYPES.includes(t),
                ) && typeof descr.isEmpty !== "function",
        )
        .map(({ key }) => key)
        .sort();

    expect(missing).toEqual([]);
});

/**
 * @type {string[]}
 */
const NO_DISPLAY_NAME_BY_DESIGN = [];

test("every registry entry names itself", () => {
    const missing = registryEntries()
        .filter(
            ({ key, descr }) =>
                !descr.displayName && !NO_DISPLAY_NAME_BY_DESIGN.includes(key),
        )
        .map(({ key }) => key)
        .sort();

    expect(missing).toEqual([]);
});

const NO_SUPPORTED_TYPES_BY_DESIGN = ["property_tags"];

test("every registry entry declares the types it supports", () => {
    const missing = registryEntries()
        .filter(
            ({ key, descr }) =>
                !descr.supportedTypes && !NO_SUPPORTED_TYPES_BY_DESIGN.includes(key),
        )
        .map(({ key }) => key)
        .sort();

    expect(missing).toEqual([]);
});
