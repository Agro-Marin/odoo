// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { click, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { CapsLockWarning } from "@web/public/caps_lock_warning";
import { ShowPassword } from "@web/public/show_password";

import { startInteraction } from "./helpers.js";

describe.current.tags("interaction_dev");

const FIELD = `
    <div class="o_caps_lock_warning">
        <input type="password"/>
    </div>`;

/**
 * @param {string} type
 * @param {{ key?: string, capsLock?: boolean }} options
 */
function keyEvent(type, { key = "a", capsLock = false } = {}) {
    const ev = new KeyboardEvent(type, { key, bubbles: true });
    ev.getModifierState = (name) => name === "CapsLock" && capsLock;
    return ev;
}

const warning = () => queryOne(".o_caps_lock_warning_text").textContent;

test("renders the live region, empty and already in the DOM", async () => {
    await startInteraction(CapsLockWarning, FIELD);
    const el = queryOne(".o_caps_lock_warning_text");
    expect(el).toHaveAttribute("role", "status");
    expect(el).toHaveAttribute("aria-live", "polite");
    expect(warning()).toBe("");
    expect(el.getBoundingClientRect().height).toBe(0);
});

test("fills the live region while caps lock is on and empties it after", async () => {
    await startInteraction(CapsLockWarning, FIELD);
    const input = queryOne(".o_caps_lock_warning input");

    input.dispatchEvent(keyEvent("keyup", { capsLock: true }));
    await animationFrame();
    expect(warning()).toBe("Caps Lock is on!");

    input.dispatchEvent(keyEvent("keyup", { capsLock: false }));
    await animationFrame();
    expect(warning()).toBe("");
});

test("the caps lock keydown itself is ignored, its keyup is not", async () => {
    await startInteraction(CapsLockWarning, FIELD);
    const input = queryOne(".o_caps_lock_warning input");

    input.dispatchEvent(keyEvent("keydown", { key: "CapsLock", capsLock: true }));
    await animationFrame();
    expect(warning()).toBe("");

    input.dispatchEvent(keyEvent("keyup", { key: "CapsLock", capsLock: true }));
    await animationFrame();
    expect(warning()).toBe("Caps Lock is on!");
});

test("an event with no modifier state leaves the warning as it was", async () => {
    await startInteraction(CapsLockWarning, FIELD);
    const input = queryOne(".o_caps_lock_warning input");
    input.dispatchEvent(keyEvent("keyup", { capsLock: true }));
    await animationFrame();
    expect(warning()).toBe("Caps Lock is on!");

    const ev = new KeyboardEvent("keyup", { key: "a", bubbles: true });
    // @ts-ignore -- deliberately removing the capability
    ev.getModifierState = undefined;
    input.dispatchEvent(ev);
    await animationFrame();
    expect(warning()).toBe("Caps Lock is on!");
});

const LOGIN_FIELD = `
    <div class="o_caps_lock_warning">
        <div class="input-group">
            <input type="password" name="password"/>
            <button type="button" class="o_show_password"><i class="fa-eye"/></button>
        </div>
    </div>`;

test("caps lock is still watched after the password has been revealed", async () => {
    await startInteraction([CapsLockWarning, ShowPassword], LOGIN_FIELD);
    const input = queryOne("input[name='password']");

    input.dispatchEvent(keyEvent("keyup", { capsLock: true }));
    await animationFrame();
    expect(warning()).toBe("Caps Lock is on!");

    await click(".o_show_password");
    await animationFrame();
    expect(input).toHaveAttribute("type", "text");
    input.dispatchEvent(keyEvent("keyup", { capsLock: false }));
    await animationFrame();
    expect(warning()).toBe("");

    await click(".o_show_password");
    await animationFrame();
    expect(input).toHaveAttribute("type", "password");
    input.dispatchEvent(keyEvent("keyup", { capsLock: true }));
    await animationFrame();
    expect(warning()).toBe("Caps Lock is on!");
});

test("the rendered warning is taken back out when the interaction stops", async () => {
    const { core } = await startInteraction(CapsLockWarning, FIELD);
    expect(".o_caps_lock_warning_text").toHaveCount(1);
    core.stopInteractions();
    expect(".o_caps_lock_warning_text").toHaveCount(0);
});
