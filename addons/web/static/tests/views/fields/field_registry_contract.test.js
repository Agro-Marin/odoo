// @ts-check

/**
 * Contract tests over the whole `fields` registry rather than any one widget.
 *
 * Both invariants were silently broken before these existed: widgets read a
 * dozen options they never declared (so Studio and the developer tooltip, which
 * are driven by `supportedOptions`, could not show them), and nothing checked
 * that a widget can actually render every type it claims in `supportedTypes`.
 */

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

/** Widgets registered without a `view.` prefix, i.e. usable from any arch. */
function genericEntries() {
    return registry
        .category("fields")
        .getEntries()
        .filter(([key]) => !key.includes("."));
}

test("every widget renders each type it claims in supportedTypes", async () => {
    const failures = [];
    let attempted = 0;

    for (const [key, descr] of genericEntries()) {
        for (const type of descr.supportedTypes || []) {
            const fieldName = FIELD_OF_TYPE[type];
            if (!fieldName) {
                continue;
            }
            attempted++;
            try {
                await mountView({
                    type: "form",
                    resModel: "partner",
                    resId: 1,
                    arch: `
                        <form>
                            <field name="currency_id" invisible="1"/>
                            <field name="${fieldName}" widget="${key}"/>
                        </form>`,
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
 * `date` and `datetime` reuse `dateField.extractProps`, which also serves
 * `daterange`; the range-only options belong to `daterange`'s declaration, not
 * to theirs. Every other entry here was real drift and has been declared.
 */
/** @type {Record<string, string[]>} */
const UNDECLARED_BY_DESIGN = {
    date: ["always_range", "end_date_field", "rounding", "start_date_field"],
    datetime: ["always_range", "end_date_field", "start_date_field"],
};

test("extractProps reads no option that supportedOptions does not declare", () => {
    const drift = [];

    for (const [key, descr] of genericEntries()) {
        if (typeof descr.extractProps !== "function") {
            continue;
        }
        const read = new Set();
        const record = (/** @type {string | symbol} */ prop) => {
            if (typeof prop === "string") {
                read.add(prop);
            }
        };
        const options = new Proxy(
            {},
            {
                get: (_target, prop) => void record(prop),
                has: (_target, prop) => (record(prop), false),
            },
        );
        try {
            descr.extractProps(
                // Deliberately a skeleton, not a full StaticFieldInfo: the
                // catch below treats "needs more than this" as out of scope.
                /** @type {any} */ ({
                    attrs: {},
                    options,
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
            // A widget whose extractProps needs more than this skeleton is out
            // of scope here rather than a failure.
            continue;
        }
        const declared = new Set([
            ...(descr.supportedOptions || []).map((/** @type {any} */ o) => o.name),
            ...(UNDECLARED_BY_DESIGN[key] || []),
        ]);
        const undeclared = [...read].filter((name) => !declared.has(name)).sort();
        if (undeclared.length) {
            drift.push(`${key}: ${undeclared.join(", ")}`);
        }
    }

    expect(drift).toEqual([]);
});
