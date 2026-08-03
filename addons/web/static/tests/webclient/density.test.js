// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import {
    defineModels,
    getService,
    makeMockEnv,
    mountWithCleanup,
    patchWithCleanup,
    webModels,
} from "@web/../tests/web_test_helpers";
import { cookie } from "@web/core/browser/cookie";
import { user } from "@web/core/user";
import { DENSITIES, nextDensity } from "@web/webclient/density/density_service";
import { DensityToggle } from "@web/webclient/density/density_toggle";

const { ResCompany, ResPartner, ResUsers, ResUsersSettings } = webModels;

// `density.set()` persists through `user.setUserSettings`, which writes to
// res.users.settings — without the model the RPC rejects and the assertions
// never run.
defineModels([ResCompany, ResPartner, ResUsers, ResUsersSettings]);

describe.current.tags("desktop");

test("nextDensity walks the declared order and wraps", () => {
    // The cycle used to be spelled out three times (DENSITIES, a re-declared
    // `order` inside cycle(), and DENSITY_META's `next:` chain). Deriving the
    // step from the one list is what keeps them from drifting.
    expect(DENSITIES.map(nextDensity)).toEqual([...DENSITIES.slice(1), DENSITIES[0]]);
});

test("nextDensity is a full cycle over every density", () => {
    const seen = [];
    let density = DENSITIES[0];
    for (let i = 0; i < DENSITIES.length; i++) {
        seen.push(density);
        density = nextDensity(density);
    }
    expect(seen).toEqual(DENSITIES);
    expect(density).toBe(DENSITIES[0]);
});

test("cycling applies the body class and records the cookie", async () => {
    await makeMockEnv();
    const density = getService("density");
    expect(density.current).toBe("default");
    expect(document.body).not.toHaveClass("o-density-compact");

    await density.cycle();
    expect(density.current).toBe("compact");
    expect(document.body).toHaveClass("o-density-compact");
    expect(cookie.get("content_density")).toBe("compact");

    await density.cycle();
    expect(density.current).toBe("condensed");
    expect(document.body).toHaveClass("o-density-condensed");
    expect(document.body).not.toHaveClass("o-density-compact");

    await density.cycle();
    expect(density.current).toBe("default");
    expect(document.body).not.toHaveClass("o-density-condensed");
});

test("an unknown density is refused", async () => {
    await makeMockEnv();
    const density = getService("density");
    await density.set("enormous");
    expect(density.current).toBe("default");
});

test("the systray toggle tracks a density set from elsewhere", async () => {
    // The toggle used to mirror `current` into its own useState and re-read it
    // only inside its own toggle(), so a density changed by anything else left
    // the icon and tooltip stale until an unrelated render.
    await makeMockEnv();
    const toggle = await mountWithCleanup(DensityToggle);
    const compactIcon = toggle.icon;

    await getService("density").set("condensed");
    await animationFrame();

    expect(toggle.icon).not.toBe(compactIcon);
    expect(toggle.icon).toBe("fa-solid fa-bars");
    expect(toggle.title).toInclude("Condensed");
    expect(toggle.title).toInclude("Default");
});

test("a failed persist rolls the density back instead of rejecting", async () => {
    // Applying optimistically and letting the persist reject left the body
    // class, the cookie and `current` on a value the server never accepted —
    // and the rejection escaped through the systray toggle's click handler.
    await makeMockEnv();
    const density = getService("density");
    patchWithCleanup(user, {
        setUserSettings: async () => {
            throw new Error("offline");
        },
    });

    let rejection = null;
    await density.set("compact").catch((error) => (rejection = error));

    expect(rejection).toBe(null);
    expect(density.current).toBe("default");
    expect(cookie.get("content_density")).toBe("default");
    expect(document.body.classList.contains("o-density-compact")).toBe(false);
});
