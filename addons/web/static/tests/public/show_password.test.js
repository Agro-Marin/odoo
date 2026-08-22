// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { click, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { ShowPassword } from "@web/public/show_password";

import { startInteraction } from "./helpers.js";

describe.current.tags("interaction_dev");

const GROUP = `
    <div class="input-group">
        <input type="password" value="hunter2"/>
        <button class="o_show_password"><i class="fa fa-eye"></i></button>
    </div>`;

test("reveals and hides the password, and says so", async () => {
    await startInteraction(ShowPassword, GROUP);
    const input = queryOne(".input-group input");
    const toggle = queryOne(".o_show_password");

    expect(input).toHaveAttribute("type", "password");
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(toggle).toHaveAttribute("aria-label", "Show password");
    expect(toggle).toHaveAttribute("title", "Show password");
    expect(".o_show_password > i").toHaveClass("fa-eye");

    await click(toggle);
    await animationFrame();
    expect(input).toHaveAttribute("type", "text");
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(toggle).toHaveAttribute("aria-label", "Hide password");
    expect(".o_show_password > i").toHaveClass("fa-eye-slash");
    expect(/** @type {HTMLInputElement} */ (input).value).toBe("hunter2");

    await click(toggle);
    await animationFrame();
    expect(input).toHaveAttribute("type", "password");
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(".o_show_password > i").toHaveClass("fa-eye");
});

test("a revealed password is hidden again when the interaction stops", async () => {
    const { core } = await startInteraction(ShowPassword, GROUP);
    await click(".o_show_password");
    await animationFrame();
    expect(".input-group input").toHaveAttribute("type", "text");
    core.stopInteractions();
    expect(".input-group input").toHaveAttribute("type", "password");
});

test("each input group toggles on its own", async () => {
    await startInteraction(ShowPassword, `${GROUP}${GROUP}`);
    const [first, second] = [...document.querySelectorAll(".input-group input")];
    await click(document.querySelectorAll(".o_show_password")[0]);
    await animationFrame();
    expect(first).toHaveAttribute("type", "text");
    expect(second).toHaveAttribute("type", "password");
});

test("a group without its own toggle is left alone", async () => {
    const { core } = await startInteraction(
        ShowPassword,
        `<div class="input-group"><input type="password"/></div>
         <div class="input-group"><div><button class="o_show_password">x</button></div></div>`,
    );
    expect(core.interactions).toHaveLength(0);
});
