import { after, expect, test } from "@odoo/hoot";
import { mockMatchMedia } from "@odoo/hoot-mock";
import {
    defineModels,
    fields,
    getMockEnv,
    mountWithCleanup,
    patchWithCleanup,
    webModels,
} from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { cookie } from "@web/core/browser/cookie";
import { _makeUser, user } from "@web/core/user";
import { MainComponentsContainer } from "@web/ui/main_components_container";

class ResUsersSettings extends webModels.ResUsersSettings {
    color_scheme = fields.Selection({
        selection: [
            ["system", "System"],
            ["light", "Light"],
            ["dark", "Dark"],
        ],
        default: "system",
    });

    _records = [
        {
            id: 1,
            color_scheme: "system",
        },
    ];
}

defineModels([ResUsersSettings]);

/**
 * Starting the service must never re-serve the page: webclient_bootstrap
 * resolves the cookie inline before any bundle runs, and both stylesheets ship
 * behind prefers-color-scheme, so there is nothing left for a reload to fix.
 */
/** @param {{ prefers: string, setting: string }} config */
async function startWith({ prefers, setting }) {
    mockMatchMedia({ ["prefers-color-scheme"]: prefers });
    patchWithCleanup(browser.location, {
        reload: () => expect.step("reloadPage"),
    });
    patchWithCleanup(
        user,
        _makeUser({ user_settings: { id: 1, color_scheme: setting } }),
    );
    ResUsersSettings._records[0].color_scheme = setting;
    // The service writes the attribute on the real document, which outlives the
    // test; restored so the next one does not inherit it.
    const initial = document.documentElement.dataset.colorScheme;
    after(() => {
        if (initial === undefined) {
            delete document.documentElement.dataset.colorScheme;
        } else {
            document.documentElement.dataset.colorScheme = initial;
        }
    });
    await mountWithCleanup(MainComponentsContainer);
}

test("use 'system' color scheme (light)", async () => {
    await startWith({ prefers: "light", setting: "system" });
    expect(cookie.get("color_scheme")).toBe("light");
    expect.verifySteps([]);
});

test("use 'system' color scheme (dark)", async () => {
    await startWith({ prefers: "dark", setting: "system" });
    expect(cookie.get("color_scheme")).toBe("dark");
    expect.verifySteps([]);
});

test("use 'light' color scheme", async () => {
    await startWith({ prefers: "dark", setting: "light" });
    expect(cookie.get("color_scheme")).toBe("light");
    expect.verifySteps([]);
});

test("use 'dark' color scheme", async () => {
    await startWith({ prefers: "light", setting: "dark" });
    expect(cookie.get("color_scheme")).toBe("dark");
    expect.verifySteps([]);
});

test("an explicit preference outranks the system one", async () => {
    await startWith({ prefers: "dark", setting: "light" });
    expect(cookie.get("color_scheme")).toBe("light");
});

test("both carriers say the same thing after start", async () => {
    // The cookie is what JS reads and the attribute what the token layer
    // answers; they are two halves of one statement. Publishing only when the
    // cookie looks wrong cannot see the case where it is the attribute that is
    // -- a template that sets one and not the other leaves the token layer
    // with no scheme at all, and nothing says so.
    delete document.documentElement.dataset.colorScheme;
    cookie.set("color_scheme", "dark");
    await startWith({ prefers: "light", setting: "dark" });
    expect(cookie.get("color_scheme")).toBe("dark");
    expect(/** @type {any} */ (document.documentElement.dataset.colorScheme)).toBe(
        "dark",
    );
    expect.verifySteps([]);
});

/**
 * A `system` user is served both stylesheets behind prefers-color-scheme, so
 * the OS switching theme repaints the page on its own. Nothing tells the cookie,
 * and every reader of it — chart palettes, the ace theme, the colour picker —
 * would keep answering with the scheme that was in effect at boot.
 */
test("a system user follows the OS switching theme", async () => {
    await startWith({ prefers: "light", setting: "system" });
    expect(cookie.get("color_scheme")).toBe("light");

    mockMatchMedia({ ["prefers-color-scheme"]: "dark" });
    expect(cookie.get("color_scheme")).toBe("dark");
    expect(document.documentElement.dataset.colorScheme).toBe("dark");
    expect.verifySteps([]);
});

// ...and stops once its env is torn down. `colorScheme` is one module-level
// carrier shared by every env, so a listener left behind does not merely leak:
// it goes on answering for an env that is gone, and in a page holding two it is
// the dead one that writes the scheme last.
test("a destroyed env stops following the OS", async () => {
    await startWith({ prefers: "light", setting: "system" });
    expect(cookie.get("color_scheme")).toBe("light");

    /** @type {any} */ (getMockEnv()).destroy();

    mockMatchMedia({ ["prefers-color-scheme"]: "dark" });
    expect(cookie.get("color_scheme")).toBe("light");
    expect(document.documentElement.dataset.colorScheme).toBe("light");
    expect.verifySteps([]);
});

test("an explicit preference ignores the OS switching theme", async () => {
    // The server picked the bundle from the setting, so the media query never
    // matched anything here — following it would contradict the stylesheet.
    await startWith({ prefers: "light", setting: "light" });
    mockMatchMedia({ ["prefers-color-scheme"]: "dark" });
    expect(cookie.get("color_scheme")).toBe("light");
    expect.verifySteps([]);
});
