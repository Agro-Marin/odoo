// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { press, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
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
import { registry } from "@web/core/registry";
import { condition, Expression } from "@web/core/tree/condition_tree";
import { constructDomainFromTree } from "@web/core/tree/construct_domain_from_tree";
import { constructTreeFromDomain } from "@web/core/tree/construct_tree_from_domain";
import { createDebugContext } from "@web/services/debug/debug_context";
import { useNavigation } from "@web/services/navigation/navigation";
import { simplifyTree } from "@web/services/tree_processor_service";
import { user } from "@web/services/user";

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
