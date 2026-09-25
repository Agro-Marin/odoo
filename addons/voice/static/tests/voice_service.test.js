// @ts-check

import { after, beforeEach, describe, expect, test } from "@odoo/hoot";
import { click, queryAllTexts, waitFor } from "@odoo/hoot-dom";
import { advanceTime, animationFrame } from "@odoo/hoot-mock";
import { AVAILABILITY_TIMEOUT_MS } from "@voice/engines/voice_engines";
import {
    contains,
    defineActions,
    defineMenus,
    defineModels,
    fields,
    getFacetTexts,
    getService,
    models,
    mountWebClient,
    onRpc,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";

describe.current.tags("desktop");

class Partner extends models.Model {
    _name = "res.partner";
    name = fields.Char();
    _records = [
        { id: 1, name: "Acme" },
        { id: 2, name: "Acme Corp" },
        { id: 3, name: "Beta" },
    ];
}

class Invoice extends models.Model {
    _name = "account.move";
    name = fields.Char({ string: "Número" });
    partner_id = fields.Many2one({ string: "Cliente", relation: "res.partner" });
    paid = fields.Boolean({ string: "Pagada" });
    _records = [
        { id: 1, name: "INV/1", partner_id: 1, paid: false },
        { id: 2, name: "INV/2", partner_id: 3, paid: true },
    ];
    _views = {
        list: `<list><field name="name"/><field name="partner_id"/></list>`,
        search: `
            <search>
                <field name="name"/>
                <field name="partner_id"/>
                <filter name="unpaid" string="Sin pagar" domain="[('paid', '=', False)]"/>
            </search>`,
    };
}

class Order extends models.Model {
    _name = "sale.order";
    name = fields.Char({ string: "Referencia" });
    partner_id = fields.Many2one({ string: "Cliente", relation: "res.partner" });
    quantity = fields.Float({ string: "Cantidad" });
    note = fields.Text({ string: "Notas" });
    _records = [{ id: 7, name: "S00042", quantity: 1 }];
    _views = {
        form: `
            <form>
                <header>
                    <button name="action_confirm" type="object" string="Confirmar"/>
                </header>
                <sheet>
                    <field name="name"/>
                    <field name="partner_id"/>
                    <field name="quantity"/>
                    <field name="note"/>
                </sheet>
            </form>`,
    };
}

defineModels([Partner, Invoice, Order]);

defineActions([
    {
        id: 10,
        xml_id: "invoices",
        name: "Facturas",
        res_model: "account.move",
        views: [[false, "list"]],
    },
    {
        id: 20,
        xml_id: "order",
        name: "Pedido",
        res_model: "sale.order",
        res_id: 7,
        views: [[false, "form"]],
    },
]);

defineMenus([
    {
        id: 1,
        name: "Contabilidad",
        appID: 1,
        actionID: 10,
        children: [{ id: 11, name: "Facturas de cliente", appID: 1, actionID: 10 }],
    },
    { id: 2, name: "Ventas", appID: 2, actionID: 20 },
]);

/** @param {boolean} acknowledged */
function setNoticeAcknowledged(acknowledged) {
    user.updateUserSettings("voice_notice_acknowledged", acknowledged);
    after(() => user.updateUserSettings("voice_notice_acknowledged", false));
}

beforeEach(() => {
    setNoticeAcknowledged(true);
    patchWithCleanup(browser, {
        SpeechRecognition: undefined,
        webkitSpeechRecognition: undefined,
    });
});

/** @param {string} text */
async function say(text) {
    await getService("voice").submit(text);
    await animationFrame();
}

async function openInvoices() {
    await mountWebClient();
    await getService("menu").selectMenu(1);
    await waitFor(".o_list_view");
}

async function openOrder() {
    await mountWebClient();
    await getService("menu").selectMenu(2);
    await waitFor(".o_form_view");
}

test("an app is opened by name, from anywhere", async () => {
    await mountWebClient();
    await say("abre contabilidad");
    await waitFor(".o_list_view");
    expect(".o_menu_brand").toHaveText("Contabilidad");
    expect(".o_voice_done_item").toHaveText("Open Contabilidad");
});

test("a sentence becomes facets, and undo takes them off", async () => {
    await openInvoices();
    await say("sin pagar");
    expect(getFacetTexts()).toEqual(["Sin pagar"]);
    await say("cliente Acme");
    expect(getFacetTexts()).toEqual(["Sin pagar", "Cliente\nAcme"]);
    await click(".o_voice_undo");
    await animationFrame();
    expect(getFacetTexts()).toEqual(["Sin pagar"]);
});

test("what follows a menu is applied to the view it opens", async () => {
    await mountWebClient();
    await say("abre facturas de cliente sin pagar");
    await waitFor(".o_list_view");
    await animationFrame();
    expect(getFacetTexts()).toEqual(["Sin pagar"]);
});

test("a spoken value is staged in the form, not saved", async () => {
    onRpc("web_save", () => expect.step("web_save"));
    await openOrder();
    await say("cantidad cinco");
    expect(".o_field_widget[name=quantity] input").toHaveValue("5.00");
    expect(".o_form_status_indicator_buttons").not.toHaveClass("invisible");
    expect.verifySteps([]);
});

test("a relation is resolved by name, and several matches ask which one", async () => {
    await openOrder();
    await say("cliente Acme");
    expect(".o_field_widget[name=partner_id] input").toHaveValue("Acme");
    await say("cliente Be");
    expect(".o_field_widget[name=partner_id] input").toHaveValue("Beta");
    await say("cliente Ac");
    expect(queryAllTexts(".o_voice_candidate")).toEqual([
        "Cliente: Acme",
        "Cliente: Acme Corp",
    ]);
    await click(".o_voice_candidate:eq(1)");
    await animationFrame();
    expect(".o_field_widget[name=partner_id] input").toHaveValue("Acme Corp");
});

test("a button waits for an explicit confirmation", async () => {
    onRpc("sale.order", "action_confirm", () => {
        expect.step("action_confirm");
        return true;
    });
    await openOrder();
    await say("confirmar");
    expect(".o_voice_confirm_label").toHaveText("Confirmar on S00042");
    expect.verifySteps([]);
    await click(".o_voice_confirm_button");
    await animationFrame();
    expect.verifySteps(["action_confirm"]);
});

test("a negation never presses a button", async () => {
    onRpc("sale.order", "action_confirm", () => expect.step("action_confirm"));
    await openOrder();
    await say("no confirmar");
    expect(".o_voice_confirm").toHaveCount(0);
    expect(".o_voice_message").toHaveText(
        "That sounded like a “no”: Confirmar on S00042 was not done.",
    );
    expect.verifySteps([]);
});

test("what is not understood shows what can be said here", async () => {
    await openInvoices();
    await say("el perro come croquetas");
    expect(".o_voice_message").toHaveText(
        "I did not understand “el perro come croquetas”.",
    );
    expect(queryAllTexts(".o_voice_example")).toInclude("Sin pagar");
});

test("the palette takes a sentence after “>”", async () => {
    await openInvoices();
    await getService("command").openMainPalette({ searchValue: ">sin pagar" });
    await waitFor(".o_command");
    expect(".o_command").toHaveText("Sin pagar");
    await click(".o_command");
    await animationFrame();
    expect(getFacetTexts()).toEqual(["Sin pagar"]);
});

test("the microphone says so when no engine can listen", async () => {
    await openInvoices();
    await click(".o_voice_systray");
    await animationFrame();
    expect(".o_voice_message").toHaveText(
        "No speech engine is available here. You can still type what you would say in the command palette, after “>”.",
    );
});

test("the first time, the microphone says where the audio goes before listening", async () => {
    setNoticeAcknowledged(false);
    onRpc("res.users.settings", "set_res_users_settings", ({ kwargs }) => {
        expect.step(Object.keys(kwargs.new_settings).join());
        return { voice_notice_acknowledged: true };
    });
    registry.category("voice_engines").add(
        "test",
        {
            available: async () => true,
            listen: async (/** @type {any} */ { onInterim }) => {
                onInterim("sin");
                return "sin pagar";
            },
            privacy: () => "Heard by a test engine.",
        },
        { sequence: 1 },
    );
    await openInvoices();
    await contains(".o_voice_systray").click();
    await waitFor(".o_voice_notice");
    expect(".o_voice_notice p:first").toHaveText("Heard by a test engine.");
    expect(getFacetTexts()).toEqual([]);
    await click(".o_voice_notice_accept");
    await animationFrame();
    await animationFrame();
    expect(getFacetTexts()).toEqual(["Sin pagar"]);
    expect.verifySteps(["voice_notice_acknowledged"]);
    registry.category("voice_engines").remove("test");
});

test("the browser engine listens on the device only, biased to what is on screen", async () => {
    /** @type {any[]} */
    const created = [];
    class FakeRecognition {
        static available = async (/** @type {any} */ options) => {
            expect.step(`available:${options.processLocally}`);
            return "available";
        };
        constructor() {
            created.push(this);
        }
        start() {
            queueMicrotask(() => {
                const result = Object.assign([{ transcript: "sin pagar" }], {
                    isFinal: true,
                });
                /** @type {any} */ (this).onresult({ results: [result] });
                /** @type {any} */ (this).onend();
            });
        }
        stop() {}
    }
    patchWithCleanup(browser, { SpeechRecognition: FakeRecognition });
    await openInvoices();
    await click(".o_voice_systray");
    await waitFor(".o_voice_done_item");
    await animationFrame();
    expect(getFacetTexts()).toEqual(["Sin pagar"]);
    expect(created[0].processLocally).toBe(true);
    expect(created[0].interimResults).toBe(true);
    expect.verifySteps(["available:true"]);
});

test("numbers are drawn on what can be clicked, and a number clicks it", async () => {
    onRpc("sale.order", "action_confirm", () => {
        expect.step("action_confirm");
        return true;
    });
    await openOrder();
    await say("muestra números");
    const voice = getService("voice");
    expect(".o_voice_number").toHaveCount(voice.targets.length);
    const confirm = voice.targets.findIndex((target) => target.label === "Confirmar");
    expect(confirm).toBeGreaterThan(-1);
    await say(String(confirm + 1));
    expect(".o_voice_confirm_label").toHaveText(`${confirm + 1}: Confirmar`);
    expect(".o_voice_number").toHaveCount(voice.targets.length, {
        message: "the numbers stay while the choice waits",
    });
    expect.verifySteps([]);
    await click(".o_voice_confirm_button");
    await animationFrame();
    expect.verifySteps(["action_confirm"]);
    expect(".o_voice_number").toHaveCount(0);
});

test("a label on screen is clicked by name", async () => {
    await openInvoices();
    await say("haz clic en New");
    await waitFor(".o_form_view");
    expect(".o_form_view .o_form_editable").toHaveCount(1);
});

test("an engine that never says whether it can listen is passed over", async () => {
    const engines = registry.category("voice_engines");
    engines.add(
        "silent",
        {
            available: () => new Promise(() => {}),
            listen: async () => "never",
            privacy: () => "",
        },
        { sequence: 1 },
    );
    engines.add(
        "answering",
        {
            available: async () => true,
            listen: async () => "sin pagar",
            privacy: () => "",
        },
        { sequence: 2 },
    );
    await openInvoices();
    await click(".o_voice_systray");
    await advanceTime(AVAILABILITY_TIMEOUT_MS);
    await waitFor(".o_voice_done_item");
    await animationFrame();
    expect(getFacetTexts()).toEqual(["Sin pagar"]);
    engines.remove("silent");
    engines.remove("answering");
});
