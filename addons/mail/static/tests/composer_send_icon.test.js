// @ts-check

import { describe, expect, getFixture, test } from "@odoo/hoot";

describe.current.tags("headless");

/**
 * The composer's send button renders `fa-regular fa-paper-plane` since the Font
 * Awesome 7 upgrade, so styling keyed on the old `fa-paper-plane-o` name no
 * longer matches and the icon loses its nudge and scale.
 */
function mountSendButton(extraButtonClass = "") {
    const fixture = getFixture();
    fixture.innerHTML = `<div class="o-mail-Composer-actions">
        <button class="${extraButtonClass}">
            <i class="fa-regular fa-paper-plane fa-lg"></i>
        </button>
    </div>`;
    return fixture.querySelector("i");
}

test("the send icon keeps its offset and scale", async () => {
    const style = getComputedStyle(mountSendButton());
    expect(style.scale).toBe("0.85");
    expect(style.transform).not.toBe("none");
});

test("the active send button paints the icon white", async () => {
    const style = getComputedStyle(mountSendButton("o-mail-Composer-send btn-link"));
    expect(style.color).toBe("rgb(255, 255, 255)");
    expect(style.scale).toBe("0.85");
});
