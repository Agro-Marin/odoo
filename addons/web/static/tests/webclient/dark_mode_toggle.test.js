import { after, expect, test } from "@odoo/hoot";
import { click } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import {
    defineModels,
    fields,
    mountWithCleanup,
    onRpc,
    patchWithCleanup,
    webModels,
} from "@web/../tests/web_test_helpers";
import { cookie } from "@web/core/browser/cookie";
import { colorScheme } from "@web/core/color_scheme";
import { _makeUser, user } from "@web/core/user";
import { colorSchemeService } from "@web/webclient/color_scheme/color_scheme_service";
import { DarkModeToggle } from "@web/webclient/dark_mode_toggle/dark_mode_toggle";

class ResUsersSettings extends webModels.ResUsersSettings {
    color_scheme = fields.Selection({
        selection: [
            ["system", "System"],
            ["light", "Light"],
            ["dark", "Dark"],
        ],
        default: "system",
    });

    _records = [{ id: 1, color_scheme: "light" }];
}

defineModels([ResUsersSettings]);

async function mountToggle(/** @type {string} */ scheme) {
    cookie.set("color_scheme", scheme);
    patchWithCleanup(
        user,
        _makeUser({ user_settings: { id: 1, color_scheme: scheme } }),
    );
    patchWithCleanup(colorSchemeService, {
        reload: () => expect.step("reload"),
    });
    await mountWithCleanup(DarkModeToggle);
}

test("toggling from light persists dark and re-serves the page", async () => {
    onRpc("res.users.settings", "set_res_users_settings", ({ kwargs }) => {
        expect.step(`set:${kwargs.new_settings.color_scheme}`);
        return {};
    });
    await mountToggle("light");
    await click(".o_dark_mode_toggle");
    await animationFrame();
    // Untouched on purpose. The cookie is the server's answer to the setting:
    // `ir_http.color_scheme` resolves it from the setting just saved, and
    // `web_client` sets it on the page this reload asks for. Writing it here
    // too would be a second writer of a value this component does not decide.
    expect(cookie.get("color_scheme")).toBe("light");
    // Persisted before the reload, or color_scheme_service would resolve the
    // setting again on the way back and undo the toggle.
    expect.verifySteps(["set:dark", "reload"]);
});

test("the in-memory user settings track the new scheme", async () => {
    // `colorSchemeService` reads `user.settings.color_scheme`, and
    // `website_enterprise` re-serves the builder rather than reloading — so a
    // reader between the write and the re-serve must not see the old value.
    onRpc("res.users.settings", "set_res_users_settings", ({ kwargs }) => ({
        color_scheme: kwargs.new_settings.color_scheme,
    }));
    await mountToggle("light");
    await click(".o_dark_mode_toggle");
    await animationFrame();
    expect(user.settings.color_scheme).toBe("dark");
    expect.verifySteps(["reload"]);
});

test("toggling from dark persists light", async () => {
    onRpc("res.users.settings", "set_res_users_settings", ({ kwargs }) => {
        expect.step(`set:${kwargs.new_settings.color_scheme}`);
        return {};
    });
    await mountToggle("dark");
    await click(".o_dark_mode_toggle");
    await animationFrame();
    expect(cookie.get("color_scheme")).toBe("dark");
    expect.verifySteps(["set:light", "reload"]);
});

test("the button follows the OS switching theme", async () => {
    // A `system` user is served both stylesheets behind prefers-color-scheme,
    // so the OS flipping repaints the page and colorSchemeService republishes
    // the scheme -- with nothing reloading. Sampled once at setup, this button
    // would then offer to switch to the mode already on screen.
    const initial = document.documentElement.dataset.colorScheme;
    after(() => {
        if (initial === undefined) {
            delete document.documentElement.dataset.colorScheme;
        } else {
            document.documentElement.dataset.colorScheme = initial;
        }
    });
    await mountToggle("light");
    expect(".o_dark_mode_toggle i").toHaveClass("fa-moon");
    expect(".o_dark_mode_toggle").toHaveAttribute("title", "Switch to dark mode");

    colorScheme.publish("dark");
    await animationFrame();
    expect(".o_dark_mode_toggle i").toHaveClass("fa-sun");
    expect(".o_dark_mode_toggle").toHaveAttribute("title", "Switch to light mode");
});

test("the reload goes through the service, not browser.location", async () => {
    // website_enterprise overrides colorSchemeService.reload() to re-enter the
    // builder instead of reloading the preview. Calling browser.location
    // directly would bypass that override.
    onRpc("res.users.settings", "set_res_users_settings", () => ({}));
    await mountToggle("light");
    await click(".o_dark_mode_toggle");
    await animationFrame();
    expect.verifySteps(["reload"]);
});
