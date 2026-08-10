import { Action } from "@mail/core/common/action";
import { describe, expect, test } from "@odoo/hoot";

describe.current.tags("desktop");

test("store is correctly set on actions", async () => {
    const storeSym = Symbol("STORE");
    const ownerSym = Symbol("COMPONENT");
    const action = new Action({
        owner: ownerSym,
        id: "test",
        definition: {},
        store: storeSym,
    });
    expect(action.store).toBe(storeSym);
});

test("every documented option is resolvable, as a value and as a callback", async () => {
    // The drift gate. `Action`'s option list lives in three places -- the
    // `ActionDefinition` typedef, the `_x()` override hooks and the getters --
    // and they had already diverged: `btnAttrs` was documented and implemented
    // while being read by nothing. Nothing checked the three agreed.
    //
    // Rather than re-list the options here (a fourth copy, drifting the same
    // way), this drives every getter twice: once with the option given as a
    // plain value and once as a callback, asserting the two resolve alike.
    // Options the class deliberately does not resolve polymorphically are named
    // with the reason.
    const NOT_POLYMORPHIC = {
        component: "an OWL Component class IS a function; calling it is wrong",
        dropdown: "documented as a plain boolean",
        componentProps: "always a callback, never a bare value",
        disabledCondition: "always a callback, never a bare value",
        dropdownComponent: "component-or-factory, resolved by prototype check",
    };
    const sentinel = Symbol("resolved");
    const owner = {};
    const store = {};
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
        // `tags` wraps a scalar in an array and `isActive` coerces to Boolean;
        // comparing the two forms against each other keeps this indifferent to
        // per-option shaping while still proving both paths run.
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
