// @ts-check

import { expect, test } from "@odoo/hoot";
import { processButton } from "@web/views/view_buttons";

/**
 * Build a `<button>` arch node from an attribute string.
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
    expect(withCtx.clickParams.context).toBe("{'a': 1}");
    expect(withCtx.clickParams.close).toBe(true);
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
