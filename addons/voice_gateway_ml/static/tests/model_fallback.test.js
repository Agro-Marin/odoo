// @ts-check

import { beforeEach, describe, expect, test } from "@odoo/hoot";
import { waitFor } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { forgetAvailability } from "@voice_gateway_ml/model_fallback";
import {
    defineActions,
    defineMenus,
    defineModels,
    fields,
    getFacetTexts,
    getService,
    models,
    mountWebClient,
    onRpc,
} from "@web/../tests/web_test_helpers";
import { user } from "@web/core/user";

describe.current.tags("desktop");

class Invoice extends models.Model {
    _name = "account.move";
    name = fields.Char();
    paid = fields.Boolean();
    _records = [{ id: 1, name: "INV/1", paid: false }];
    _views = {
        list: `<list><field name="name"/></list>`,
        search: `<search><filter name="unpaid" string="Sin pagar" domain="[('paid', '=', False)]"/></search>`,
    };
}
defineModels([Invoice]);
defineActions([
    { id: 10, name: "Facturas", res_model: "account.move", views: [[false, "list"]] },
]);
defineMenus([{ id: 1, name: "Contabilidad", appID: 1, actionID: 10 }]);

beforeEach(() => {
    forgetAvailability();
    user.updateUserSettings("voice_notice_acknowledged", true);
});

async function openInvoices() {
    await mountWebClient();
    await getService("menu").selectMenu(1);
    await waitFor(".o_list_view");
}

test("what the grammar did not understand is asked of the model", async () => {
    onRpc("/voice_gateway_ml/available", () => ({ available: true }));
    onRpc("/voice_gateway_ml/interpret", async (request) => {
        const { params } = await request.json();
        expect.step(params.text);
        expect(params.choices.map((/** @type {any} */ c) => c.id)).toInclude(
            "filter:unpaid",
        );
        return { actions: [{ id: "filter:unpaid", value: "" }] };
    });
    await openInvoices();
    await getService("voice").submit("muéstrame lo que no han pagado");
    await animationFrame();
    expect(getFacetTexts()).toEqual(["Sin pagar"]);
    expect(".o_voice_done_item .o_voice_from_model").toHaveCount(1);
    expect.verifySteps(["muéstrame lo que no han pagado"]);
});

test("the grammar answers first, and an unconfigured model is not asked", async () => {
    onRpc("/voice_gateway_ml/available", () => {
        expect.step("available");
        return { available: false };
    });
    onRpc("/voice_gateway_ml/interpret", () => expect.step("interpret"));
    await openInvoices();
    await getService("voice").submit("sin pagar");
    await animationFrame();
    expect(getFacetTexts()).toEqual(["Sin pagar"]);
    expect.verifySteps([]);
    await getService("voice").submit("muéstrame lo que no han pagado");
    await getService("voice").submit("y lo de ayer");
    await animationFrame();
    expect.verifySteps(["available"]);
    expect(".o_voice_message").toHaveText("I did not understand “y lo de ayer”.");
});
