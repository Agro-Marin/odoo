// @ts-check

import { expect, test } from "@odoo/hoot";
import { animationFrame, runAllTimers } from "@odoo/hoot-mock";
import { Component, xml } from "@odoo/owl";
import { getService, mountWithCleanup } from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/registry";
import { CommandPalette } from "@web/ui/commands/command_palette";
import { MainComponentsContainer } from "@web/ui/main_components_container";

class Fragile extends Component {
    static template = xml`<div class="row-ok"/>`;
    static props = ["*"];
    setup() {
        if (this.props.explode) {
            throw new Error("row exploded");
        }
    }
}

/**
 * @param {{ name: string, explode?: boolean }[]} specs
 * @returns {Promise<number>}
 */
async function openPaletteWith(specs) {
    const config = {
        configByNamespace: { default: { categories: ["default"] } },
        providers: [
            {
                provide: () =>
                    specs.map((spec) => ({
                        Component: Fragile,
                        action: () => {},
                        category: "default",
                        name: spec.name,
                        props: { explode: Boolean(spec.explode) },
                    })),
            },
        ],
    };
    const close = getService("dialog").add(CommandPalette, { config });
    await animationFrame();
    await runAllTimers();
    await animationFrame();
    await animationFrame();
    await animationFrame();
    const survivors = document.querySelectorAll(".row-ok").length;
    await close();
    await animationFrame();
    return survivors;
}

test("a broken command does not take its same-named sibling with it", async () => {
    expect.errors(1);
    await mountWithCleanup(MainComponentsContainer);

    const survivors = await openPaletteWith([
        { name: "same name", explode: true },
        { name: "same name" },
    ]);
    expect.verifyErrors([/row exploded/]);
    expect(survivors).toBe(1);
});

test("distinct names are unaffected (the control for the above)", async () => {
    expect.errors(1);
    await mountWithCleanup(MainComponentsContainer);
    const survivors = await openPaletteWith([
        { name: "name A", explode: true },
        { name: "name B" },
    ]);
    expect.verifyErrors([/row exploded/]);
    expect(survivors).toBe(1);
});

test("an identical twin of a broken command is still filtered", async () => {
    expect.errors(1);
    await mountWithCleanup(MainComponentsContainer);

    const survivors = await openPaletteWith([
        { name: "same name", explode: true },
        { name: "same name", explode: true },
    ]);
    expect.verifyErrors([/row exploded/]);
    expect(survivors).toBe(0);
});

test("a registered command can be a link", async () => {
    await mountWithCleanup(MainComponentsContainer);
    const commandService = /** @type {any} */ (getService("command"));
    commandService.add("open the thing", () => {}, {
        global: true,
        href: "/odoo/somewhere",
        className: "o_my_command",
    });
    await animationFrame();

    const provided = registry
        .category("command_provider")
        .get("command")
        .provide(commandService.env, { activeElement: document })
        .find((/** @type {any} */ c) => c.name === "open the thing");

    expect(provided.href).toBe("/odoo/somewhere");
    expect(provided.className).toBe("o_my_command");
});

test("the palette renders the link a registered command asked for", async () => {
    await mountWithCleanup(MainComponentsContainer);
    /** @type {any} */ (getService("command")).add("open the thing", () => {}, {
        global: true,
        href: "/odoo/somewhere",
        className: "o_my_command",
    });
    await animationFrame();

    /** @type {any} */ (getService("command")).openMainPalette();
    await animationFrame();
    await runAllTimers();
    await animationFrame();

    expect(".o_command a[href='/odoo/somewhere'].o_my_command").toHaveCount(1);
});

test("the palette placeholder is a string, not a lazy translation", async () => {
    await mountWithCleanup(MainComponentsContainer);
    /** @type {any} */ (getService("command")).openMainPalette();
    await animationFrame();
    await runAllTimers();
    await animationFrame();

    const input = document.querySelector(".o_command_palette input");
    expect(input?.getAttribute("placeholder")).toBe("Search for a command...");
});
