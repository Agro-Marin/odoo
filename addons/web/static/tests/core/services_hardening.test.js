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

class Host extends Component {
    static props = [];
    static template = xml`<div class="host"/>`;
}

describe("list-operator values", () => {
    test("a bracket-less `in` candidate survives the domain round trip", () => {
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
        const tree = condition("geo_point", "in", "{ACTIVE_IDS}");
        expect(tree.value).toBe("{ACTIVE_IDS}");
        expect(constructDomainFromTree(tree)).toBe(
            `[("geo_point", "in", "{ACTIVE_IDS}")]`,
        );
    });

    test("an Expression `in` is neither wrapped nor merged", () => {
        const tree = constructTreeFromDomain(
            `["|", ("id", "in", allowed_ids), ("id", "=", 1)]`,
        );
        expect(tree.children[0].value instanceof Expression).toBe(true);
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
        expect(queryOne(".o-navigable.wrapper")).not.toHaveAttribute("aria-selected");
        expect(queryOne(".o-navigable.wrapper .inner")).not.toHaveAttribute(
            "aria-selected",
        );
    });

    test("an item's own id is never overwritten by the generated one", async () => {
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
        expect(listbox.id).toBe("o_command_palette_listbox");
        expect(input.getAttribute("aria-controls")).toBe(listbox.id);
        expect(
            document.getElementById(input.getAttribute("aria-activedescendant")),
        ).not.toBe(null);
    });
});

describe("field paths are data, not property names", () => {
    test("an OR of `=` on a `__proto__` path merges instead of throwing", () => {
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
        const { connectionRecoveryService } =
            await import("@web/core/network/connection_recovery_service");

        const makeError = () => {
            const error = new UncaughtPromiseError();
            error.unhandledRejectionEvent = { preventDefault: () => {} };
            return error;
        };
        // One service instance per env is now what makes this per-env, rather
        // than a module-level WeakMap keyed by env that nothing owned.
        const makeEnv = (opened) => {
            const env = { services: { dialog: { add: () => opened.push(1) } } };
            env.services.connection_recovery = connectionRecoveryService.start(env);
            return env;
        };
        const expired = new InvalidResponseError("/web/x", 200);

        const firstEnvDialogs = [];
        const firstEnv = makeEnv(firstEnvDialogs);
        lostConnectionHandler(firstEnv, makeError(), expired);
        lostConnectionHandler(firstEnv, makeError(), expired);
        expect(firstEnvDialogs).toHaveLength(1);

        const secondEnvDialogs = [];
        lostConnectionHandler(makeEnv(secondEnvDialogs), makeError(), expired);
        expect(secondEnvDialogs).toHaveLength(1);
    });
});

describe("property names are data, not property names", () => {
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
        expect(changes.length).toBe(1);
        picker.dispose();
    });
});

describe("reconnect poll stops with its env", () => {
    test("destroying the env cancels the pending reconnect probe", async () => {
        const { UncaughtPromiseError } =
            await import("@web/core/errors/uncaught_errors");
        const { ConnectionLostError } = await import("@web/core/network/rpc");
        const { lostConnectionHandler } =
            await import("@web/components/errors/error_handlers");
        const { connectionRecoveryService } =
            await import("@web/core/network/connection_recovery_service");
        await makeMockEnv();
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
        env.services.connection_recovery = recovery;
        expect(lostConnectionHandler(env, error, new ConnectionLostError("/x"))).toBe(
            true,
        );
        expect(notifications).toEqual(["Connection lost. Trying to reconnect..."]);

        recovery.destroy();
        await advanceTime(120_000);
        expect.verifySteps([]);
        expect(notifications).toEqual(["Connection lost. Trying to reconnect..."]);
    });
});
