import { expect, test } from "@odoo/hoot";
import {
    defineModels,
    defineWebModels,
    fields,
    models,
    mountView,
} from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/registry";

class MatchLine extends models.Model {
    _name = "match.line";
    name = fields.Char();
    amount = fields.Monetary({ currency_field: "currency_id" });
    currency_id = fields.Many2one({ relation: "res.currency" });
    _records = [
        { id: 1, name: "M0001", amount: 0, currency_id: 1 },
        { id: 2, name: "M0002", amount: 12.5, currency_id: 1 },
    ];
}

defineWebModels();
defineModels([MatchLine]);

test("monetary_no_zero blanks a stored zero but keeps a non-zero", async () => {
    await mountView({
        type: "list",
        resModel: "match.line",
        arch: `<list>
                 <field name="amount" widget="monetary_no_zero"/>
                 <field name="currency_id" column_invisible="1"/>
               </list>`,
    });
    const cells = [...document.querySelectorAll("td[name=amount]")].map((el) =>
        el.textContent.trim(),
    );
    expect(cells[0]).toBe("", { message: "stored 0.0 renders blank" });
    expect(cells[1]).not.toBe("", { message: "non-zero still renders" });
});

test("monetary_no_zero has its own label and an isEmpty matching the render", () => {
    const noZero = registry.category("fields").get("monetary_no_zero");
    const plain = registry.category("fields").get("monetary");
    expect(noZero.displayName).not.toBe(plain.displayName, {
        message: "two picker entries both labelled 'Monetary' is unusable",
    });
    expect(noZero.isEmpty({ data: { amount: 0 } }, "amount")).toBe(true, {
        message: "a zero renders blank, so isEmpty must agree it is empty",
    });
    expect(noZero.isEmpty({ data: { amount: 3 } }, "amount")).toBe(false);
});

test("open_match_line resolves its target from the record, not a hardcoded model", () => {
    const field = registry.category("fields").get("open_match_line");
    expect(field.supportedTypes).toEqual(["char"]);
    const source = field.component.prototype.openMatchLine.toString();
    expect(source).toInclude("this.props.record.resModel");
    expect(source).not.toMatch(/resModel:\s*"/);
});
