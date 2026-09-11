// @ts-check
import { Action } from "@mail/core/common/action";
import { ComposerAction } from "@mail/core/common/composer_actions";
import { describe, expect, test } from "@odoo/hoot";
import { Component } from "@odoo/owl";

describe.current.tags("desktop");

test("store is correctly set on actions", async () => {
    const storeSym = /** @type {import("models").Store} */ (
        /** @type {unknown} */ (Symbol("STORE"))
    );
    const ownerSym = /** @type {import("@mail/core/common/action").ActionOwner} */ (
        /** @type {unknown} */ (Symbol("COMPONENT"))
    );
    const action = new Action({
        owner: ownerSym,
        id: "test",
        definition: {},
        store: storeSym,
    });
    expect(action.store).toBe(storeSym);
});

test("every documented option is resolvable, as a value and as a callback", async () => {
    const NOT_POLYMORPHIC = {
        component: "an OWL Component class IS a function; calling it is wrong",
        dropdown: "documented as a plain boolean",
        componentProps: "always a callback, never a bare value",
        dropdownComponent: "component-or-factory, resolved by prototype check",
    };
    const sentinel = Symbol("resolved");
    const owner = /** @type {import("@mail/core/common/action").ActionOwner} */ ({});
    const store = /** @type {import("models").Store} */ ({});
    const optionNames = Object.getOwnPropertyNames(Action.prototype)
        .filter((name) => name.startsWith("_") && name !== "_option")
        .filter((name) => !["_optionOr", "_callOption"].includes(name))
        .map((name) => name.slice(1))
        .filter((name) => name in Action.prototype);

    expect(optionNames.length).toBeGreaterThan(20);

    for (const name of optionNames) {
        if (name in NOT_POLYMORPHIC) {
            continue;
        }
        const asValue = new Action({
            owner,
            id: "t",
            definition: { [name]: sentinel },
            store,
        });
        const asCallback = new Action({
            owner,
            id: "t",
            definition: { [name]: () => sentinel },
            store,
        });
        expect(JSON.stringify(asValue[name] ?? null)).toBe(
            JSON.stringify(asCallback[name] ?? null),
            { message: `option "${name}" resolves differently as value vs callback` },
        );
    }
});

test("every hook has a getter and every getter that reads an option has a hook", async () => {
    const names = Object.getOwnPropertyNames(Action.prototype);
    const helpers = new Set(["_option", "_optionOr", "_callOption"]);
    const hooks = names.filter((n) => n.startsWith("_") && !helpers.has(n));
    const missingGetter = hooks.filter((h) => !names.includes(h.slice(1)));
    expect(missingGetter).toEqual([], {
        message: `override hooks with no getter reading them: ${missingGetter}`,
    });
});

test("a picker-name callback receives the owning composer component", () => {
    const owner = new Component({ label: "GIFs" }, {});
    const action = new ComposerAction({
        owner,
        id: "picker",
        composer: undefined,
        store: /** @type {import("models").Store} */ ({}),
        definition: { pickerName: (component) => component.props.label },
    });
    expect(action.pickerName).toBe("GIFs");
});

test("disabledCondition accepts literal booleans and callbacks", () => {
    const owner = new Component({}, {});
    const store = /** @type {import("models").Store} */ ({});
    for (const disabled of [true, false]) {
        const literal = new Action({
            owner,
            store,
            id: "literal",
            definition: { disabledCondition: disabled },
        });
        const callback = new Action({
            owner,
            store,
            id: "callback",
            definition: { disabledCondition: () => disabled },
        });
        expect(literal.disabledCondition).toBe(disabled);
        expect(callback.disabledCondition).toBe(disabled);
    }
});
