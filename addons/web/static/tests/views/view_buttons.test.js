// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { queryAll } from "@odoo/hoot-dom";
import {
    contains,
    defineModels,
    fields,
    models,
    mountView,
    webModels,
} from "@web/../tests/web_test_helpers";
import { processButton } from "@web/views/view_buttons";

const { ResCompany, ResPartner, ResUsers } = webModels;

class Partner extends models.Model {
    _name = "partner";
    name = fields.Char();
    _records = [{ id: 1, name: "one" }];
}

defineModels([Partner, ResCompany, ResPartner, ResUsers]);

/**
 * @param {string} attrs
 * @returns {Element}
 */
function buttonNode(attrs) {
    return new DOMParser().parseFromString(`<button ${attrs}/>`, "text/xml")
        .documentElement;
}

test("processButton splits action params from visual attrs", () => {
    const res = processButton(
        buttonNode(`name="action_confirm" type="object" data-hotkey="q"`),
    );
    expect(res.clickParams).toEqual({ name: "action_confirm", type: "object" });
    expect(res.attrs).toEqual({ "data-hotkey": "q" });
});

test("processButton extracts string/icon/title fields", () => {
    const res = processButton(
        buttonNode(
            `name="x" type="object" string="Confirm" icon="fa-check" title="Tip"`,
        ),
    );
    expect(res.string).toBe("Confirm");
    expect(res.icon).toBe("fa-check");
    expect(res.title).toBe("Tip");
});

test("processButton applies context/close defaults only when the attribute is present", () => {
    const withCtx = processButton(
        buttonNode(`name="x" type="object" context="{'a': 1}" close="1"`),
    );
    const clickParams = /** @type {Record<string, any>} */ (withCtx.clickParams);
    expect(clickParams.context).toBe("{'a': 1}");
    expect(clickParams.close).toBe(true);
});

test("processButton parses a valid options attribute", () => {
    const res = processButton(
        buttonNode(
            `name="x" type="object" options="{&quot;mode&quot;: &quot;edit&quot;}"`,
        ),
    );
    expect(res.options).toEqual({ mode: "edit" });
});

test("processButton raises a contextual error for malformed options (L3)", () => {
    expect(() =>
        processButton(buttonNode(`name="x" type="object" options="{not json}"`)),
    ).toThrow(/Invalid JSON in button "options" attribute/);
});

test("processButton ORs column_invisible into invisible", () => {
    const res = processButton(
        buttonNode(`name="x" type="object" column_invisible="1"`),
    );
    expect(res.column_invisible).toBe("1");
    expect(Boolean(res.invisible)).toBe(true);
});

describe("processButton — the disabled contract", () => {
    /**
     * @param {string} value
     * @returns {boolean}
     */
    function buttonDisabled(value) {
        return processButton(buttonNode(`name="x" type="object" disabled="${value}"`))
            .disabled;
    }

    test(`disabled="1" disables the button`, () => {
        expect(buttonDisabled("1")).toBe(true);
    });

    test(`disabled="0" does NOT disable the button`, () => {
        expect(buttonDisabled("0")).toBe(false);
    });

    test(`disabled="False" does NOT disable the button`, () => {
        expect(buttonDisabled("False")).toBe(false);
    });

    test(`disabled="" does NOT disable the button`, () => {
        expect(buttonDisabled("")).toBe(false);
    });

    test(`disabled="disabled" disables the button`, () => {
        expect(buttonDisabled("disabled")).toBe(true);
    });

    test("an absent disabled attribute leaves the button enabled", () => {
        expect(processButton(buttonNode(`name="x" type="object"`)).disabled).toBe(
            false,
        );
    });
});

test("processButton keeps arch vocabulary out of the DOM passthrough bag", () => {
    const res = processButton(
        buttonNode(
            `name="x" type="object" string="S" class="c" icon="fa-check" title="T"` +
                ` invisible="1" readonly="0" required="1" column_invisible="0"` +
                ` disabled="1" display="always" data-hotkey="q" width="80"`,
        ),
    );
    expect(res.attrs).toEqual({ "data-hotkey": "q", width: "80" });
    expect(res.modifiers).toEqual({
        invisible: "1",
        readonly: "0",
        required: "1",
        column_invisible: "0",
    });
    expect(res.className).toBe("c");
    expect(res.string).toBe("S");
    expect(res.disabled).toBe(true);
});

test.tags("desktop");
test("a header button carries no arch vocabulary into the DOM", async () => {
    await mountView({
        resModel: "partner",
        type: "list",
        arch: `<list>
                <header>
                    <button name="h" type="object" string="H" class="my_c"
                        invisible="0" readonly="1" data-hotkey="q"/>
                </header>
                <field name="name"/>
            </list>`,
    });
    await contains(".o_list_record_selector input").click();
    const button = queryAll("button[name='h']")[0];
    expect(
        [...button.attributes]
            .map((attribute) => attribute.name)
            .sort()
            .join(" "),
    ).toBe("class data-hotkey name type");
    expect(button.className).toInclude("my_c");
});

test.tags("desktop");
test("a compiled form button carries no arch vocabulary into the DOM", async () => {
    await mountView({
        resModel: "partner",
        type: "form",
        resId: 1,
        arch: `<form>
                <button name="b" type="object" string="B" class="my_c"
                    invisible="0" readonly="1" data-hotkey="q"/>
                <field name="name"/>
            </form>`,
    });
    const button = queryAll("button[name='b']")[0];
    expect(
        [...button.attributes]
            .map((attribute) => attribute.name)
            .sort()
            .join(" "),
    ).toBe("class data-hotkey name type");
});
