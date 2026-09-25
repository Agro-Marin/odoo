// @ts-check

import { beforeEach, describe, expect, test } from "@odoo/hoot";
import { click, waitFor } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { Dictation } from "@speech/live_capture/dictation";
import { withDictated } from "@speech_voice/dictate_executor";
import {
    defineActions,
    defineMenus,
    defineModels,
    fields,
    getService,
    models,
    mountWebClient,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { user } from "@web/core/user";

describe.current.tags("desktop");

class Order extends models.Model {
    _name = "sale.order";
    name = fields.Char({ string: "Referencia" });
    note = fields.Text({ string: "Notas" });
    _records = [{ id: 7, name: "S00042", note: "Llamó el cliente." }];
    _views = {
        form: `<form><field name="name"/><field name="note"/></form>`,
    };
}

defineModels([Order]);
defineActions([
    {
        id: 20,
        xml_id: "order",
        name: "Pedido",
        res_model: "sale.order",
        res_id: 7,
        views: [[false, "form"]],
    },
]);
defineMenus([{ id: 2, name: "Ventas", appID: 2, actionID: 20 }]);

/** @type {any[]} */
let dictations;

beforeEach(() => {
    dictations = [];
    user.updateUserSettings("voice_notice_acknowledged", true);
    patchWithCleanup(browser, {
        SpeechRecognition: undefined,
        webkitSpeechRecognition: undefined,
    });
    patchWithCleanup(Dictation.prototype, {
        async start(target) {
            dictations.push(this);
            /** @type {any} */ (this).target = target;
        },
        async stop() {
            /** @type {any} */ (this).stopped = true;
        },
    });
});

test("text and html receive dictated words differently", () => {
    expect(withDictated("Hola", "mundo", "text")).toBe("Hola mundo");
    expect(withDictated(false, "mundo", "char")).toBe("mundo");
    expect(String(withDictated("<p>a</p>", "b & c", "html"))).toBe(
        "<p>a</p><p>b &amp; c</p>",
    );
    expect(withDictated("Hola", "", "text")).toBe("Hola");
});

test("a field fills in as the words arrive, until the dictation is stopped", async () => {
    await mountWebClient();
    await getService("menu").selectMenu(2);
    await waitFor(".o_form_view");
    await getService("voice").submit("dicta notas");
    await animationFrame();
    expect(".o_voice_session_label").toHaveText("Dictating into Notas");
    const [dictation] = dictations;
    expect(dictation.target).toMatchObject({ resModel: "sale.order", resId: 7 });

    dictation.onChunkText(1, " y pidió factura ");
    dictation.onChunkText(0, "Confirmó el pedido");
    await animationFrame();
    expect(".o_field_widget[name=note] textarea").toHaveValue(
        "Llamó el cliente. Confirmó el pedido y pidió factura",
    );

    await click(".o_voice_session_stop");
    await animationFrame();
    expect(dictation.stopped).toBe(true);
    expect(".o_voice_session").toHaveCount(0);

    await click(".o_voice_undo");
    await animationFrame();
    expect(".o_field_widget[name=note] textarea").toHaveValue("Llamó el cliente.");
});

test("the microphone button stops a dictation instead of listening", async () => {
    await mountWebClient();
    await getService("menu").selectMenu(2);
    await waitFor(".o_form_view");
    await getService("voice").submit("dicta notas");
    await animationFrame();
    expect(".o_voice_systray").toHaveClass("text-danger");
    await click(".o_voice_systray");
    await animationFrame();
    expect(dictations[0].stopped).toBe(true);
    expect(".o_voice_systray").not.toHaveClass("text-danger");
});
