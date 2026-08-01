// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { CapsLockWarning } from "@web/public/caps_lock_warning";

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
    // jsdom-style events carry no modifier state; the interaction reads it
    // through getModifierState and bails out when it is unavailable
    ev.getModifierState = (name) => name === "CapsLock" && capsLock;
    return ev;
}

test("renders the warning, hidden, next to the field", async () => {
    await startInteraction(CapsLockWarning, FIELD);
    expect(".o_caps_lock_warning_text").toHaveCount(1);
    expect(".o_caps_lock_warning_text").toHaveClass("d-none");
});

test("shows the warning while caps lock is on and hides it after", async () => {
    await startInteraction(CapsLockWarning, FIELD);
    const input = queryOne(".o_caps_lock_warning input");

    input.dispatchEvent(keyEvent("keyup", { capsLock: true }));
    await animationFrame();
    expect(".o_caps_lock_warning_text").not.toHaveClass("d-none");

    input.dispatchEvent(keyEvent("keyup", { capsLock: false }));
    await animationFrame();
    expect(".o_caps_lock_warning_text").toHaveClass("d-none");
});

test("the caps lock keydown itself is ignored, its keyup is not", async () => {
    await startInteraction(CapsLockWarning, FIELD);
    const input = queryOne(".o_caps_lock_warning input");

    // pressing the key down reports the state *before* the toggle in some
    // browsers, so only the keyup may be trusted for that key
    input.dispatchEvent(keyEvent("keydown", { key: "CapsLock", capsLock: true }));
    await animationFrame();
    expect(".o_caps_lock_warning_text").toHaveClass("d-none");

    input.dispatchEvent(keyEvent("keyup", { key: "CapsLock", capsLock: true }));
    await animationFrame();
    expect(".o_caps_lock_warning_text").not.toHaveClass("d-none");
});

test("an event with no modifier state leaves the warning as it was", async () => {
    await startInteraction(CapsLockWarning, FIELD);
    const input = queryOne(".o_caps_lock_warning input");
    input.dispatchEvent(keyEvent("keyup", { capsLock: true }));
    await animationFrame();
    expect(".o_caps_lock_warning_text").not.toHaveClass("d-none");

    const ev = new KeyboardEvent("keyup", { key: "a", bubbles: true });
    // @ts-ignore -- deliberately removing the capability
    ev.getModifierState = undefined;
    input.dispatchEvent(ev);
    await animationFrame();
    expect(".o_caps_lock_warning_text").not.toHaveClass("d-none");
});

test("the rendered warning is taken back out when the interaction stops", async () => {
    const { core } = await startInteraction(CapsLockWarning, FIELD);
    expect(".o_caps_lock_warning_text").toHaveCount(1);
    core.stopInteractions();
    expect(".o_caps_lock_warning_text").toHaveCount(0);
});
