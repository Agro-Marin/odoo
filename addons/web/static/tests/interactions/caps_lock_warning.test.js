// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { keyDown, keyUp, pointerDown, queryOne } from "@odoo/hoot-dom";
import {
    setupInteractionWhiteList,
    startInteractions,
} from "@web/../tests/public/helpers";

setupInteractionWhiteList("web.caps_lock_warning");

describe.current.tags("interaction_dev");

const template = `
    <div class="mb-3 field-password pt-2 o_caps_lock_warning">
        <label for="password" class="form-label">Password</label>
        <div class="input-group mb-1">
            <input type="password" name="password" id="password"
            class="form-control"/>
        </div>
    </div>`;

/** @param {boolean} on */
const caps = (on) => ({ modifierCapsLock: on });

test("caps_lock_warning is started when there is a presence of password input field inside `.o_caps_lock_warning`", async () => {
    const { core } = await startInteractions(template);
    expect(core.interactions).toHaveLength(1);
});

test("caps lock alert is displayed when CapsLock is turned on", async () => {
    await startInteractions(template);
    await pointerDown(queryOne("#password"));
    await keyDown("CapsLock", caps(true));
    await keyUp("CapsLock", caps(true));
    expect(".o_caps_lock_warning_text").toBeVisible();
});

test("caps lock alert is hidden again when CapsLock is turned off", async () => {
    await startInteractions(template);
    await pointerDown(queryOne("#password"));
    await keyUp("CapsLock", caps(true));
    expect(".o_caps_lock_warning_text").toBeVisible();

    await keyDown("CapsLock", caps(false));
    await keyUp("CapsLock", caps(false));
    expect(".o_caps_lock_warning_text").not.toBeVisible();
});

test("typing an ordinary key reflects the current CapsLock state", async () => {
    await startInteractions(template);
    await pointerDown(queryOne("#password"));

    await keyDown("a", caps(true));
    expect(".o_caps_lock_warning_text").toBeVisible();

    await keyDown("a", caps(false));
    expect(".o_caps_lock_warning_text").not.toBeVisible();
});

test("the ambiguous CapsLock keydown never flips the warning on its own", async () => {
    await startInteractions(template);
    await pointerDown(queryOne("#password"));
    await keyUp("CapsLock", caps(true));
    expect(".o_caps_lock_warning_text").toBeVisible();

    await keyDown("CapsLock", caps(false));
    expect(".o_caps_lock_warning_text").toBeVisible();
});
