// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { press, queryOne } from "@odoo/hoot-dom";
import { advanceTime, animationFrame } from "@odoo/hoot-mock";
import { Component, onMounted, xml } from "@odoo/owl";
import {
    defineModels,
    fields,
    getService,
    makeMockEnv,
    models,
    mountWithCleanup,
    onRpc,
} from "@web/../tests/web_test_helpers";
import { createDebugContext } from "@web/core/debug/debug_context";
import { useNavigation } from "@web/core/navigation/navigation";
import { registry } from "@web/core/registry";
import { condition, Expression } from "@web/core/tree/condition_tree";
import { constructDomainFromTree } from "@web/core/tree/construct_domain_from_tree";
import { constructTreeFromDomain } from "@web/core/tree/construct_tree_from_domain";
import { simplifyTree } from "@web/core/tree/tree_processor_service";
import { user } from "@web/core/user";

class Hardening extends models.Model {
    _name = "hardening";
    state = fields.Char({ string: "State" });
    qty = fields.Integer({ string: "Qty" });
    manager_id = fields.Many2one({ string: "Manager", relation: "hardening" });
}
defineModels([Hardening]);

describe.current.tags("desktop");

/** Bare mount target, so services needing a main container have one. */
class Host extends Component {
    static props = [];
    static template = xml`<div class="host"/>`;
}

describe("list-operator values", () => {
    test("a bracket-less `in` candidate survives the domain round trip", () => {
        // Deliberately NOT repaired into `["draft"]`: geoengine stores
        // `("geo_point", "in", "{ACTIVE_IDS}")` and matches the placeholder by
        // strict equality, so rewriting the value here silently stripped its
        // virtual operator.
        const tree = constructTreeFromDomain([["state", "in", "draft"]]);
        expect(tree.value).toBe("draft");
        expect(constructDomainFromTree(tree)).toBe(`[("state", "in", "draft")]`);
    });

    test("a geo placeholder domain round-trips through the tree untouched", () => {
        const tree = constructTreeFromDomain([["geo_point", "in", "{ACTIVE_IDS}"]]);
        expect(tree.value).toBe("{ACTIVE_IDS}");
        expect(constructDomainFromTree(tree)).toBe(
            `[("geo_point", "in", "{ACTIVE_IDS}")]`,
        );
    });

    test("merging an OR of `=`/`in` no longer explodes a string into characters", async () => {
        await makeMockEnv();
        const treeProcessor = getService("tree_processor");
        const tree = await treeProcessor.treeFromDomain("hardening", [
            "|",
            ["state", "in", "draft"],
            ["state", "=", "done"],
        ]);
        // Unmergeable, so each condition renders on its own instead of the
        // string being spread into `d or r or a or f or t`.
        expect(await treeProcessor.getDomainTreeDescription("hardening", tree)).toBe(
            "State = draft or State = done",
        );
    });

    test("a numeric `in` candidate no longer throws out of the description", async () => {
        await makeMockEnv();
        const treeProcessor = getService("tree_processor");
        const tree = await treeProcessor.treeFromDomain("hardening", [
            "|",
            ["qty", "in", 5],
            ["qty", "=", 1],
        ]);
        expect(await treeProcessor.getDomainTreeDescription("hardening", tree)).toBe(
            "Qty = 5 or Qty = 1",
        );
    });

    test("condition() leaves a caller's explicit scalar alone", () => {
        // The repair belongs to untrusted domain TEXT. `geoengine` builds
        // `condition(path, "in", "{ACTIVE_IDS}")` with a scalar placeholder on
        // purpose; wrapping it emitted a domain its substitution step no longer
        // recognises.
        const tree = condition("geo_point", "in", "{ACTIVE_IDS}");
        expect(tree.value).toBe("{ACTIVE_IDS}");
        expect(constructDomainFromTree(tree)).toBe(
            `[("geo_point", "in", "{ACTIVE_IDS}")]`,
        );
    });

    test("an Expression `in` is neither wrapped nor merged", () => {
        // As domain TEXT, so `allowed_ids` parses as a name rather than a string.
        const tree = constructTreeFromDomain(
            `["|", ("id", "in", allowed_ids), ("id", "=", 1)]`,
        );
        expect(tree.children[0].value instanceof Expression).toBe(true);
        // Unmergeable: its members are a server value, so the OR is preserved
        // rather than flattened into a list that omits them.
        expect(simplifyTree(tree).type).toBe("connector");
        expect(constructDomainFromTree(tree)).toBe(
            `["|", ("id", "in", allowed_ids), ("id", "=", 1)]`,
        );
    });
});

describe("hotkey canonicalisation", () => {
    test("modifier order and key position no longer decide whether it fires", async () => {
        await makeMockEnv();
        const hotkey = getService("hotkey");
        for (const spec of [
            "alt+shift+u",
            "shift+alt+u",
            "u+alt+shift",
            "alt+alt+shift+u",
        ]) {
            let fired = false;
            const remove = hotkey.add(spec, () => (fired = true), { global: true });
            await animationFrame();
            await press(["alt", "shift", "u"]);
            remove();
            expect(fired).toBe(true, { message: `${spec} should fire` });
        }
    });

    test("canonicalisation does not weaken validation", async () => {
        await makeMockEnv();
        const hotkey = getService("hotkey");
        expect(() => hotkey.add("alt+a+b", () => {})).toThrow(/more than one/);
        expect(() => hotkey.add("alt+notakey", () => {})).toThrow(/not whitelisted/);
    });
});

describe("navigation accessibility", () => {
    class MenuParent extends Component {
        static props = [];
        static template = xml`
            <div class="container" role="menu" t-ref="containerRef">
                <div class="o-navigable wrapper" role="menuitem"><button class="inner">one</button></div>
                <div class="o-navigable second" role="menuitem"><button>two</button></div>
            </div>
        `;
        setup() {
            this.navigation = useNavigation("containerRef", {});
            onMounted(() => this.navigation.items[0]?.setActive());
        }
    }

    test("the active item is published through aria-activedescendant", async () => {
        await makeMockEnv();
        await mountWithCleanup(MenuParent);
        await animationFrame();
        const container = queryOne(".container");
        const wrapper = queryOne(".o-navigable.wrapper");
        expect(wrapper.id).toMatch(/^o-navigation-item-\d+$/);
        expect(container.getAttribute("aria-activedescendant")).toBe(wrapper.id);
    });

    test("aria-selected is not stamped on a role that does not support it", async () => {
        await makeMockEnv();
        await mountWithCleanup(MenuParent);
        await animationFrame();
        // A `menuitem` has no `aria-selected` in ARIA; the container element and
        // its inner target used to carry contradicting values at the same time.
        expect(queryOne(".o-navigable.wrapper")).not.toHaveAttribute("aria-selected");
        expect(queryOne(".o-navigable.wrapper .inner")).not.toHaveAttribute(
            "aria-selected",
        );
    });

    test("an item's own id is never overwritten by the generated one", async () => {
        // The generated id is a DOM mutation on an element another component
        // owns. `search_bar` reads it back with `Number.parseInt(itemEl.id)` to
        // recover its item, so clobbering a caller's id would resolve to NaN.
        class OwnIds extends Component {
            static props = [];
            static template = xml`
                <div class="container" role="menu" t-ref="containerRef">
                    <div id="42" class="o-navigable first" role="menuitem" tabindex="0">one</div>
                    <div id="43" class="o-navigable second" role="menuitem" tabindex="0">two</div>
                </div>`;
            setup() {
                this.navigation = useNavigation("containerRef", {});
                onMounted(() => this.navigation.items[0]?.setActive());
            }
        }
        await makeMockEnv();
        await mountWithCleanup(OwnIds);
        await animationFrame();
        expect(queryOne(".o-navigable.first").id).toBe("42");
        expect(queryOne(".container").getAttribute("aria-activedescendant")).toBe("42");
        await press("arrowdown");
        await animationFrame();
        expect(queryOne(".o-navigable.second").id).toBe("43");
        expect(queryOne(".container").getAttribute("aria-activedescendant")).toBe("43");
    });

    test("aria-activedescendant follows the selection and clears with it", async () => {
        await makeMockEnv();
        const parent = await mountWithCleanup(MenuParent);
        await animationFrame();
        const container = queryOne(".container");
        const second = queryOne(".o-navigable.second");
        await press("arrowdown");
        await animationFrame();
        expect(container.getAttribute("aria-activedescendant")).toBe(second.id);

        parent.navigation._setActiveItem(-1);
        expect(container).not.toHaveAttribute("aria-activedescendant");
    });
});

describe("caches and memoisation", () => {
    test("checkAccessRight keys on the id SET, not the caller's ordering", async () => {
        await makeMockEnv();
        let calls = 0;
        onRpc("has_access", () => {
            calls++;
            return true;
        });
        await user.checkAccessRight("hardening", "read", [1, 2]);
        await user.checkAccessRight("hardening", "read", [2, 1]);
        await user.checkAccessRight("hardening", "read", [1, 2, 2]);
        expect(calls).toBe(1);
    });

    test("a debug category resolves to its innermost context", async () => {
        await makeMockEnv();
        onRpc("has_access", () => true);
        const holder = createDebugContext({ categories: [] });
        const debugContext = holder[Object.getOwnPropertySymbols(holder)[0]];
        const seen = [];
        registry
            .category("debug")
            .category("hardening_cat")
            .add("probe", (params) => {
                seen.push({ marker: params.marker, outerOnly: params.outerOnly });
                return null;
            });
        debugContext.activateCategory("hardening_cat", {
            marker: "outer",
            outerOnly: "leaked",
        });
        debugContext.activateCategory("hardening_cat", { marker: "inner" });
        await debugContext.getItems({});
        registry.category("debug").category("hardening_cat").remove("probe");
        expect(seen).toEqual([{ marker: "inner", outerOnly: undefined }]);
    });
});

describe("combobox popup association", () => {
    test("the command palette input names the listbox it controls", async () => {
        await makeMockEnv();
        await mountWithCleanup(Host);
        getService("command").openMainPalette();
        await animationFrame();
        await animationFrame();
        const input = queryOne(".o_command_palette input[role=combobox]");
        const listbox = queryOne(".o_command_palette [role=listbox]");
        // Without `aria-controls` the input's `aria-activedescendant` points
        // into a popup assistive technology cannot associate with the combobox.
        expect(listbox.id).toBe("o_command_palette_listbox");
        expect(input.getAttribute("aria-controls")).toBe(listbox.id);
        expect(
            document.getElementById(input.getAttribute("aria-activedescendant")),
        ).not.toBe(null);
    });
});

describe("field paths are data, not property names", () => {
    // A field path reaches the client as free-form text: stored `ir.filters`
    // domains, action domains, `<field>` widget options, the tree editor
    // mid-edit. Every map keyed by one of those must answer "is this a declared
    // field" and not "does Object.prototype happen to have this member".

    test("an OR of `=` on a `__proto__` path merges instead of throwing", () => {
        // `childrenByPath["__proto__"]` read back `Object.prototype` — truthy,
        // so the accumulator entry was never created and the very next
        // `.elems.push(...)` threw, taking down every rendering of the domain.
        const merged = simplifyTree(
            constructTreeFromDomain([
                "|",
                ["__proto__", "=", 1],
                ["__proto__", "=", 2],
            ]),
        );
        expect(merged.type).toBe("condition");
        expect(merged.path).toBe("__proto__");
        expect(merged.operator).toBe("in");
        expect(merged.value).toEqual([1, 2]);
    });

    test("a `constructor` path resolves to no field definition", async () => {
        await makeMockEnv();
        const { fieldDef } = await getService("field").loadFieldInfo(
            "hardening",
            "constructor",
        );
        // `fields_get()["constructor"]` is `Object`, which every consumer
        // downstream then read as a field definition: `loadPath` reported the
        // path VALID and the domain description rendered a field that does not
        // exist on the model.
        expect(fieldDef).toBe(null);
    });

    test("the tree processor's field-def lookup honours its null contract", async () => {
        await makeMockEnv();
        const treeProcessor = getService("tree_processor");
        const tree = constructTreeFromDomain([
            "|",
            ["constructor", "=", 1],
            ["state", "=", "draft"],
        ]);
        const getFieldDef = await treeProcessor.makeGetFieldDef("hardening", tree);
        expect(getFieldDef("constructor")).toBe(null);
        // A real field on the same tree still resolves, so the guard narrows
        // nothing beyond the names that were never declared.
        expect(getFieldDef("state")?.type).toBe("char");
    });

    test("a `toString` path describes as unknown rather than as a field", async () => {
        await makeMockEnv();
        const { isInvalid, displayNames } = await getService(
            "field",
        ).loadPathDescription("hardening", "toString");
        expect(isInvalid).toBe(true);
        expect(displayNames).toEqual(["toString"]);
    });
});

describe("malformed condition values", () => {
    // `constructTreeFromDomain` does not validate operators, so a stored
    // `ir.filters` domain, an action domain or the debug code editor can hand
    // the renderer an `in range` whose value is not the 4-tuple the branch
    // reads. The description is produced client-side, before any server ever
    // rejects the domain.
    const BAD_IN_RANGE_VALUES = [
        ["a scalar string", "not-an-array", "State is in not-an-array"],
        ["a number", 42, "State is in 42"],
        ["an empty list", [], "State is in "],
        ["a short list", ["date"], "State is in date"],
        [
            "an unknown range type",
            ["char", "no such range", false, false],
            "State is in no such range",
        ],
    ];
    for (const [label, value, expected] of BAD_IN_RANGE_VALUES) {
        test(`an \`in range\` carrying ${label} renders instead of throwing`, async () => {
            await makeMockEnv();
            const treeProcessor = getService("tree_processor");
            const tree = constructTreeFromDomain([["state", "=", "x"]]);
            tree.operator = "in range";
            tree.value = value;
            // A scalar indexed at [1] yields a CHARACTER ("State is in o"); a
            // short list yields `undefined`, and `undefined.toString()` threw
            // out of the whole description.
            expect(
                await treeProcessor.getDomainTreeDescription("hardening", tree),
            ).toBe(expected);
        });
    }

    test("a well-formed `in range` is still read as a range", async () => {
        await makeMockEnv();
        const treeProcessor = getService("tree_processor");
        const tree = constructTreeFromDomain([["state", "=", "x"]]);
        tree.operator = "in range";
        tree.value = ["char", "today", false, false];
        // The guard must narrow nothing for the shape the tree editor produces.
        expect(await treeProcessor.getDomainTreeDescription("hardening", tree)).toBe(
            "State is in Today",
        );
    });
});

describe("connection recovery is per env", () => {
    test("a session-expired dialog left open by one env does not silence the next", async () => {
        const { UncaughtPromiseError } =
            await import("@web/core/errors/uncaught_errors");
        const { InvalidResponseError } = await import("@web/core/network/rpc");
        const { lostConnectionHandler } =
            await import("@web/components/errors/error_handlers");

        const makeError = () => {
            const error = new UncaughtPromiseError();
            error.unhandledRejectionEvent = { preventDefault: () => {} };
            return error;
        };
        const makeEnv = (opened) => ({
            services: { dialog: { add: () => opened.push(1) } },
        });
        const expired = new InvalidResponseError("/web/x", 200);

        const firstEnvDialogs = [];
        const firstEnv = makeEnv(firstEnvDialogs);
        lostConnectionHandler(firstEnv, makeError(), expired);
        lostConnectionHandler(firstEnv, makeError(), expired);
        // Same env: the second occurrence is deduplicated onto the open dialog.
        expect(firstEnvDialogs).toHaveLength(1);

        // A different env (next webclient, embedded app, next test) must not
        // inherit the first one's "a dialog is already open" flag — that flag
        // was module-level, so an env whose dialog never emitted `onClose`
        // silenced the session-expired prompt for everyone after it.
        const secondEnvDialogs = [];
        lostConnectionHandler(makeEnv(secondEnvDialogs), makeError(), expired);
        expect(secondEnvDialogs).toHaveLength(1);
    });
});

describe("property names are data, not property names", () => {
    // A property's `name` is USER-CHOSEN and the ORM's validator is
    // `^[a-z0-9_]+$` (odoo/orm/validation.py), which accepts `__proto__` and
    // `constructor`. Verified against a live database: the server stores such a
    // definition and `get_properties_base_definition` hands it straight back.
    class Holder extends models.Model {
        _name = "holder";
        properties_base_definition_id = fields.Many2one({
            relation: "properties.base.definition",
        });
        properties = fields.Properties({
            string: "Properties",
            definition_record: "properties_base_definition_id",
            definition_record_field: "properties_definition",
        });
    }
    class BaseDef extends models.Model {
        _name = "properties.base.definition";
        properties_definition = fields.Char();
    }
    defineModels([Holder, BaseDef]);

    const serverPayload = () => ({
        records: [
            {
                id: 1,
                display_name: "Holder Properties",
                properties_definition: [
                    { name: "__proto__", type: "char", string: "Proto Prop" },
                    { name: "normal_prop", type: "char", string: "Normal Prop" },
                ],
            },
        ],
    });

    test("a property named `__proto__` survives the definitions map", async () => {
        await makeMockEnv();
        onRpc(
            "/web/dataset/call_kw/properties.base.definition/get_properties_base_definition",
            serverPayload,
        );
        const definitions = await getService("field").loadPropertyDefinitions(
            "holder",
            "properties",
        );
        // On a plain object, `definitions["__proto__"] = {...}` invokes the
        // prototype SETTER: the entry is dropped and the definition object's
        // prototype becomes the property definition itself.
        expect(Object.keys(definitions)).toEqual(["__proto__", "normal_prop"]);
        expect(definitions["__proto__"].string).toBe("Proto Prop");
    });

    test("no other property name inherits the injected definition's members", async () => {
        await makeMockEnv();
        onRpc(
            "/web/dataset/call_kw/properties.base.definition/get_properties_base_definition",
            serverPayload,
        );
        const definitions = await getService("field").loadPropertyDefinitions(
            "holder",
            "properties",
        );
        // Measured before the fix: `definitions.type` was "char" and
        // `definitions.string` was "Proto Prop" — a lookup for a property named
        // `type` or `string` silently answered with the injected one's values.
        for (const polluted of ["type", "string", "name", "searchable", "record_id"]) {
            expect(definitions[polluted]).toBe(undefined, {
                message: `definitions.${polluted} must not be inherited`,
            });
        }
    });

    test("loadPropertyDefinitions names the contract a caller broke", async () => {
        await makeMockEnv();
        await expect(
            getService("field").loadPropertyDefinitions("holder", "nosuchfield"),
        ).rejects.toThrow(/has no field "nosuchfield"/);
    });
});

describe("input bindings are per owner", () => {
    class InputHost extends Component {
        static props = [];
        static template = xml`<div class="host"><input class="shared"/></div>`;
    }

    /** @param {any[]} sink */
    const makePicker = (sink) =>
        getService("datetime_picker").create({
            target: queryOne(".host"),
            getInputs: () => [queryOne("input.shared"), null],
            pickerProps: { type: "date" },
            onChange: (value) => sink.push(String(value)),
        });

    test("disposing one picker does not deafen another on the same input", async () => {
        await makeMockEnv();
        await mountWithCleanup(InputHost);
        const first = [];
        const second = [];
        const firstPicker = makePicker(first);
        firstPicker.enable();
        const secondPicker = makePicker(second);
        secondPicker.enable();
        firstPicker.dispose();

        const input = queryOne("input.shared");
        input.value = "02/20/2020";
        input.dispatchEvent(new Event("change"));

        // A module-level "already listened" registry used to make the second
        // picker attach nothing, then let the first one's dispose remove the
        // only real listeners — leaving an alive, enabled picker permanently
        // deaf. Measured before the fix: second.length === 0.
        expect(second.length).toBe(1);
        expect(first.length).toBe(0);
        secondPicker.dispose();
    });

    test("one picker enabled twice still fires exactly once", async () => {
        await makeMockEnv();
        await mountWithCleanup(InputHost);
        const changes = [];
        const picker = makePicker(changes);
        picker.enable();
        picker.enable();
        const input = queryOne("input.shared");
        input.value = "03/10/2020";
        input.dispatchEvent(new Event("change"));
        // `enable()` detaches its previous binding first, which is what makes
        // the shared registry unnecessary rather than merely harmful.
        expect(changes.length).toBe(1);
        picker.dispose();
    });
});

describe("reconnect poll stops with its env", () => {
    test("destroying the env cancels the pending reconnect probe", async () => {
        const { UncaughtPromiseError } =
            await import("@web/core/errors/uncaught_errors");
        const { ConnectionLostError } = await import("@web/core/network/rpc");
        const { lostConnectionHandler, connectionRecoveryService } =
            await import("@web/components/errors/error_handlers");
        await makeMockEnv();
        // The probe must SUCCEED, otherwise the poll only ever reschedules and
        // the assertion below cannot tell a cancelled chain from a live one.
        onRpc("/web/webclient/version_info", () => {
            expect.step("probe");
            return {};
        });

        const error = new UncaughtPromiseError();
        error.unhandledRejectionEvent = { preventDefault: () => {} };
        const notifications = [];
        const env = {
            services: {
                notification: {
                    add: (message) => {
                        notifications.push(String(message));
                        return () => {};
                    },
                },
            },
        };

        const recovery = connectionRecoveryService.start(env);
        expect(lostConnectionHandler(env, error, new ConnectionLostError("/x"))).toBe(
            true,
        );
        expect(notifications).toEqual(["Connection lost. Trying to reconnect..."]);

        // The poll re-armed itself with `setTimeout` until the server answered
        // and nothing could stop it: a torn-down env kept probing
        // `/web/webclient/version_info` for the life of the page and then
        // pushed "Connection restored" into a UI nobody displays.
        recovery.destroy();
        await advanceTime(120_000);
        expect.verifySteps([]);
        expect(notifications).toEqual(["Connection lost. Trying to reconnect..."]);
    });
});
