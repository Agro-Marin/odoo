// @ts-check

/**
 * Regression guards for the services audit fixes. Each test pins a
 * behaviour that was verified broken beforehand; the comment on each names the
 * failure it prevents.
 */

import { describe, expect, test } from "@odoo/hoot";
import { animationFrame, Deferred, press } from "@odoo/hoot-dom";
import {
    defineModels,
    fields,
    getService,
    makeMockEnv,
    models,
    mountWithCleanup,
    onRpc,
    patchWithCleanup,
    serverState,
} from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { cookie } from "@web/core/browser/cookie";
import { getCurrencyRates } from "@web/core/currency";
import { UserEvent } from "@web/core/events";
import {
    _resetFeatureFlagsCache,
    clearFeatureFlag,
    featureFlag,
    setFeatureFlag,
} from "@web/core/feature_flags";
import { _makeUser, user, userBus } from "@web/core/user";
import {
    CommandPalette,
    MAX_DISPLAYED_COMMANDS,
} from "@web/ui/commands/command_palette";
import { MainComponentsContainer } from "@web/ui/main_components_container";

class Currency extends models.Model {
    _name = "res.currency";
    name = fields.Char();
    inverse_rate = fields.Float();
    date = fields.Date();
    _records = [{ id: 1, name: "USD", inverse_rate: 1, date: "2026-07-10" }];
}

class BaseDefinition extends models.Model {
    _name = "properties.base.definition";
    display_name = fields.Char();
    properties_definition = fields.PropertiesDefinition();
    _records = [{ id: 1, display_name: "Base", properties_definition: [] }];
}

class Pet extends models.Model {
    _name = "pet";
    name = fields.Char();
    base_def_id = fields.Many2one({ relation: "properties.base.definition" });
    props = fields.Properties({
        definition_record: "base_def_id",
        definition_record_field: "properties_definition",
    });
}

defineModels([Currency, BaseDefinition, Pet]);

/** @param {number} companyId */
function accessError(companyId) {
    return {
        data: {
            name: "odoo.exceptions.AccessError",
            context: { suggested_company: { id: companyId } },
        },
    };
}

describe("multi_company_recovery", () => {
    test("save-error recovery propagates the child companies into the model context", async () => {
        // The model context wins on the retried save. It used to receive only
        // `suggested_company.id` while `activateCompanies` additionally pulled in
        // that company's children, so a record owned by a child kept failing with
        // the same AccessError the recovery was meant to clear.
        await makeMockEnv();
        patchWithCleanup(cookie, { set: () => {}, get: () => "" });
        patchWithCleanup(
            user,
            _makeUser({
                uid: 2,
                user_context: {},
                user_companies: {
                    current_company: 1,
                    allowed_companies: {
                        1: { id: 1, name: "A", child_ids: [] },
                        3: { id: 3, name: "B", child_ids: [4] },
                        4: { id: 4, name: "B child", child_ids: [] },
                    },
                },
            }),
        );
        const model = { config: { context: {} } };

        expect(
            getService("multi_company_recovery").recoverFromSaveError(
                accessError(3),
                model,
            ),
        ).toBe(true);
        expect(user.activeCompanies.map((c) => c.id)).toEqual([1, 3, 4]);
        expect(model.config.context.allowed_company_ids).toEqual([1, 3, 4]);
    });

    test("save-error recovery keeps a model-scoped company the user has not active", async () => {
        // The union must not regress into an overwrite: a form scoped to company
        // 3 must keep it even though it is absent from the user's companies.
        await makeMockEnv();
        patchWithCleanup(user, {
            get activeCompanies() {
                return [{ id: 1 }];
            },
            activateCompanies() {},
        });
        const model = { config: { context: { allowed_company_ids: [1, 3] } } };

        expect(
            getService("multi_company_recovery").recoverFromSaveError(
                accessError(2),
                model,
            ),
        ).toBe(true);
        expect(model.config.context.allowed_company_ids).toEqual([1, 3, 2]);
    });
});

describe("field_service", () => {
    test("base definitions resolve by (model, field) and ignore the caller domain", async () => {
        // Pins the contract deliberately: `search_properties_mixin` passes
        // `["id", "=", active_id]` for the OTHER branch, where definitions hang
        // off a real parent record. `properties.base.definition` has no such
        // parent — `active_id` is an id of the action's model — so forwarding
        // the domain would filter by an unrelated id and return nothing.
        await makeMockEnv();
        /** @type {any[]} */
        const calls = [];
        onRpc(
            "properties.base.definition",
            "get_properties_base_definition",
            ({ args, kwargs }) => {
                calls.push({ args, kwargs });
                return {
                    length: 1,
                    records: [
                        {
                            id: 1,
                            display_name: "Base",
                            properties_definition: [{ name: "p1", type: "char" }],
                        },
                    ],
                };
            },
        );
        const field = getService("field");

        const withDomain = await field.loadPropertyDefinitions("pet", "props", [
            ["id", "=", 42],
        ]);
        const withoutDomain = await field.loadPropertyDefinitions("pet", "props");

        expect(withDomain).toEqual(withoutDomain, {
            message: "the domain changes nothing for base definitions",
        });
        expect(Object.keys(withDomain)).toEqual(["p1"]);
        expect(calls.map((c) => c.args)).toEqual([
            ["pet", "props"],
            ["pet", "props"],
        ]);
    });
});

describe("command_palette", () => {
    test("a synchronously throwing provider does not take down the palette", async () => {
        // `Promise.allSettled` only contains rejections; a sync throw escaped the
        // map and propagated to `onWillStart`, losing every other provider.
        await mountWithCleanup(MainComponentsContainer);
        patchWithCleanup(console, { error: () => {} });
        getService("dialog").add(CommandPalette, {
            config: {
                providers: [
                    {
                        provide: () => {
                            throw new Error("sync explosion");
                        },
                    },
                    {
                        provide: async () => {
                            throw new Error("async explosion");
                        },
                    },
                    { provide: () => [{ name: "survivor", action: () => {} }] },
                ],
            },
        });
        await animationFrame();
        await animationFrame();

        expect(".o_command_palette").toHaveCount(1);
        expect(".o_command").toHaveCount(1);
        expect(".o_command").toHaveText(/survivor/);
    });

    test("overflow past the render cap is reported, not silently dropped", async () => {
        await mountWithCleanup(MainComponentsContainer);
        const total = MAX_DISPLAYED_COMMANDS + 50;
        getService("dialog").add(CommandPalette, {
            config: {
                providers: [
                    {
                        provide: () =>
                            Array.from({ length: total }, (_, i) => ({
                                name: `command ${i}`,
                                action: () => {},
                            })),
                    },
                ],
            },
        });
        await animationFrame();
        await animationFrame();

        expect(".o_command").toHaveCount(MAX_DISPLAYED_COMMANDS);
        expect(".o_command_palette_truncated").toHaveCount(1);
        expect(".o_command_palette_truncated").toHaveText(/50 more results/);
    });

    test("no truncation notice when everything fits", async () => {
        await mountWithCleanup(MainComponentsContainer);
        getService("dialog").add(CommandPalette, {
            config: {
                providers: [{ provide: () => [{ name: "only", action: () => {} }] }],
            },
        });
        await animationFrame();
        await animationFrame();

        expect(".o_command").toHaveCount(1);
        expect(".o_command_palette_truncated").toHaveCount(0);
    });
});

describe("feature_flags", () => {
    test("setFeatureFlag round-trips every FeatureFlagValue shape", async () => {
        // `String(value)` was not an inverse of `_parseValue`: the parser
        // reserves "true"/"false"/"null"/""/numeric tokens, so a string flag with
        // one of those shapes came back as the literal instead.
        _resetFeatureFlagsCache();
        patchWithCleanup(browser.location, { href: "http://localhost/odoo" });

        for (const value of [
            true,
            false,
            null,
            5,
            -1.5,
            "true",
            "false",
            "null",
            "",
            "42",
            "plain",
            " padded ",
        ]) {
            setFeatureFlag("audit_rt", /** @type {any} */ (value));
            expect(featureFlag("audit_rt")).toBe(value, {
                message: `round-trip of ${JSON.stringify(value)}`,
            });
            clearFeatureFlag("audit_rt");
        }
    });

    test("URL and localStorage still parse bare tokens as before", async () => {
        _resetFeatureFlagsCache();
        patchWithCleanup(browser.location, {
            href: "http://localhost/odoo?features=a,-b,c:7,d:hello",
        });
        expect(featureFlag("a")).toBe(true);
        expect(featureFlag("b")).toBe(false);
        expect(featureFlag("c")).toBe(7);
        expect(featureFlag("d")).toBe("hello");
        expect(featureFlag("absent", { default: null })).toBe(null);
    });
});

describe("title_service", () => {
    test("`current` reflects the service state, not a hijacked document.title", async () => {
        await makeMockEnv();
        const title = getService("title");
        title.setParts({ zopenerp: "Odoo", action: "Sales" });
        expect(title.current).toBe("Odoo - Sales");

        document.title = "hijacked by a third party";
        expect(title.current).toBe("Odoo - Sales");
        expect(title.getParts()).toEqual({ zopenerp: "Odoo", action: "Sales" });
    });
});

describe("currency", () => {
    test("a fetch issued before a company switch cannot land after it", async () => {
        // Rates are expressed against the ACTIVE company's currency, so an
        // in-flight fetch belongs to the company that issued it. Landing it
        // afterwards wrote the OLD company's conversions over the shared object,
        // with no further trigger to correct them.
        await makeMockEnv();
        serverState.currencies = [{ id: 1, position: "after", symbol: "€" }];
        let companyCurrency = 1;
        patchWithCleanup(user, {
            get activeCompany() {
                return { id: 1, currency_id: companyCurrency };
            },
        });
        const serverReplied = new Deferred();
        onRpc("read", async ({ model }) => {
            if (model !== "res.currency") {
                return;
            }
            const rate = companyCurrency === 1 ? 0.5 : 0.99;
            expect.step(`read to_currency=${companyCurrency}`);
            if (companyCurrency !== 1) {
                await serverReplied;
            }
            return [{ id: 1, inverse_rate: rate, date: "2026-07-10" }];
        });

        const rates = await getCurrencyRates();
        expect(rates[1].toCompanyRate).toBe(0.5);
        expect.verifySteps(["read to_currency=1"]);

        // A fetch for company 2 goes out, then the active companies change again
        // while it is still on the wire.
        companyCurrency = 2;
        const inFlight = getCurrencyRates();
        userBus.trigger(UserEvent.ACTIVE_COMPANIES_CHANGED);
        serverReplied.resolve();
        await inFlight;

        expect.verifySteps(["read to_currency=2"]);
        expect(rates[1].toCompanyRate).toBe(0.5, {
            message: "the superseded fetch did NOT overwrite the shared rates",
        });
    });

    test("a company switch does not by itself cost an RPC", async () => {
        // The switch changes `to_currency`, hence the rpc cache key, so the next
        // consumer call refetches on its own. Firing one here would tax every
        // company switch on pages that never show a monetary conversion.
        await makeMockEnv();
        serverState.currencies = [{ id: 1, position: "after", symbol: "€" }];
        onRpc("read", ({ model }) => {
            if (model === "res.currency") {
                expect.step("read rates");
            }
        });
        userBus.trigger(UserEvent.ACTIVE_COMPANIES_CHANGED);
        await animationFrame();
        expect.verifySteps([]);
    });
});

describe("hotkey_service", () => {
    // CONTRACT test, not a regression guard: verified to pass both with and
    // without the `registrationsByHotkey` cleanup in `unregisterHotkey`, because
    // re-registering reuses the emptied Set either way. That cleanup is memory
    // hygiene with no observable behaviour, so it is not testable behaviourally;
    // this pins the re-registration contract the cleanup must not break.
    test("a hotkey re-registered after full unregistration still dispatches", async () => {
        await makeMockEnv();
        const hotkey = getService("hotkey");
        hotkey.add("alt+z", () => expect.step("first"), { global: true })();
        hotkey.add("alt+z", () => expect.step("second"), { global: true })();
        await animationFrame();

        const remove = hotkey.add("alt+z", () => expect.step("third"), {
            global: true,
        });
        await animationFrame();
        await press(["alt", "z"]);
        expect.verifySteps(["third"]);
        remove();

        await press(["alt", "z"]);
        expect.verifySteps([]);
    });
});
