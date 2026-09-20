import "@web/webclient/actions/action_install_kiosk_pwa";

import { describe, expect, test } from "@odoo/hoot";
import { queryOne } from "@odoo/hoot-dom";
import {
    defineModels,
    fields,
    getService,
    models,
    mountWebClient,
    onRpc,
} from "@web/../tests/web_test_helpers";

class Kiosk extends models.Model {
    _name = "kiosk";
    name = fields.Char();
    _records = [{ id: 7, name: "Lobby" }];
}
defineModels([Kiosk]);

describe.current.tags("desktop");

test("the kiosk installer asks the record for its url and builds the scoped-app link from it", async () => {
    onRpc("kiosk", "get_kiosk_url", ({ args }) => {
        expect.step(`get_kiosk_url ${args[0]}`);
        return `${document.location.origin}/kiosk/7/abc`;
    });
    await mountWebClient();
    await getService("action").doAction({
        type: "ir.actions.client",
        tag: "install_kiosk_pwa",
        target: "new",
        res_model: "kiosk",
        context: { active_id: 7 },
    });
    expect.verifySteps(["get_kiosk_url 7"]);
    expect(".o_dialog a[target=_blank]:first").toHaveText(
        `${document.location.origin}/kiosk/7/abc`,
    );
    expect(queryOne(".o_dialog footer a.btn-primary").getAttribute("href")).toBe(
        "/scoped_app?app_id=kiosk&path=kiosk%2F7%2Fabc",
    );
});

test("the scoped app id comes from the context when the action names one", async () => {
    onRpc("kiosk", "get_kiosk_url", () => `${document.location.origin}/k`);
    await mountWebClient();
    await getService("action").doAction({
        type: "ir.actions.client",
        tag: "install_kiosk_pwa",
        target: "new",
        res_model: "kiosk",
        context: { active_id: 7, app_id: "frontdesk" },
    });
    expect(queryOne(".o_dialog footer a.btn-primary").getAttribute("href")).toBe(
        "/scoped_app?app_id=frontdesk&path=k",
    );
});
