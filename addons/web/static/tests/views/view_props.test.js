// @ts-check

import { expect, test } from "@odoo/hoot";
import { validate } from "@odoo/owl";
import { fieldProps } from "@web/fields/field";
import { standardFieldProps } from "@web/fields/standard_field_props";
import { STANDARD_PROPS, viewProps } from "@web/views/view";

test("every STANDARD_PROPS key carries a declared type in viewProps", () => {
    const undeclared = STANDARD_PROPS.filter((key) => !(key in viewProps));
    expect(undeclared).toEqual([], {
        message:
            `these props are consumed by View (so they are NOT forwarded to the ` +
            `controller) but have no declared type, so passing the wrong thing ` +
            `for one of them is silent: ${undeclared.join(", ")}`,
    });
});

test("viewProps stays open, so unknown props still reach the controller", () => {
    expect(viewProps["*"]).toBe(true, {
        message:
            `loadView forwards every non-STANDARD_PROPS key onward; a closed ` +
            `schema would reject callers doing exactly that`,
    });
    expect(() =>
        validate(
            { resModel: "res.partner", type: "list", someAddonProp: 42 },
            viewProps,
        ),
    ).not.toThrow();
});

test("viewProps rejects a wrongly-typed known prop", () => {
    expect(() =>
        validate({ resModel: "res.partner", type: "list" }, viewProps),
    ).not.toThrow();
    expect(() =>
        validate({ resModel: "res.partner", type: "list", domain: "[]" }, viewProps),
    ).toThrow();
    expect(() =>
        validate(
            { resModel: "res.partner", type: "list", loadIrFilters: "yes" },
            viewProps,
        ),
    ).toThrow();
    expect(() =>
        validate({ resModel: "res.partner", type: "list", groupBy: [1, 2] }, viewProps),
    ).toThrow();
});

test("resModel and type stay optional so setup() owns those two messages", () => {
    expect(() => validate({}, viewProps)).not.toThrow();
});

test("fieldProps extends standardFieldProps and stays open", () => {
    for (const key of Object.keys(standardFieldProps)) {
        expect(key in fieldProps).toBe(true, {
            message: `Field must keep validating the standard field prop "${key}"`,
        });
    }
    expect(fieldProps["*"]).toBe(true);
    expect(() =>
        validate({ name: "foo", record: {}, someWidgetOption: true }, fieldProps),
    ).not.toThrow();
});

test("fieldProps rejects a wrongly-typed prop Field itself reads", () => {
    expect(() => validate({ name: "foo", record: {} }, fieldProps)).not.toThrow();
    expect(() => validate({ name: 42, record: {} }, fieldProps)).toThrow();
    expect(() =>
        validate({ name: "foo", record: {}, readonly: "1" }, fieldProps),
    ).toThrow();
    expect(() =>
        validate({ name: "foo", record: {}, fieldInfo: "nope" }, fieldProps),
    ).toThrow();
    expect(() => validate({ name: "foo" }, fieldProps)).toThrow();
});
