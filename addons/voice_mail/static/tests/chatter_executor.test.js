// @ts-check

import {
    click,
    contains,
    defineMailModels,
    openFormView,
    start,
    startServer,
} from "@mail/../tests/mail_test_helpers";
import { beforeEach, describe, expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { getService, onRpc } from "@web/../tests/web_test_helpers";
import { user } from "@web/core/user";

describe.current.tags("desktop");
defineMailModels();

beforeEach(() => {
    user.updateUserSettings("voice_notice_acknowledged", true);
});

test("a spoken note waits in the log-note composer, and undo takes it out", async () => {
    onRpc("/mail/message/post", () => expect.step("posted"));
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "Acme" });
    await start();
    await openFormView("res.partner", partnerId);
    await contains(".o-mail-Chatter-logNote:enabled");
    await getService("voice").submit("nota: llamó el cliente, quiere factura");
    await animationFrame();
    await contains("button.active", { text: "Log note" });
    await contains(".o-mail-Composer-input", {
        value: "llamó el cliente, quiere factura",
    });
    expect.verifySteps([]);
    await click(".o_voice_undo");
    await contains(".o-mail-Composer-input", { value: "" });
});

test("a spoken message goes to the message composer, after what it held", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({ name: "Acme" });
    await start();
    await openFormView("res.partner", partnerId);
    await click("button", { text: "Send message" });
    await contains(".o-mail-Composer-input");
    getService("mail.store").Thread.insert({
        model: "res.partner",
        id: partnerId,
    }).composer.composerText = "Hola,";
    await getService("voice").submit("mensaje su pedido está listo");
    await animationFrame();
    await contains("button.active", { text: "Send message" });
    await contains(".o-mail-Composer-input", { value: "Hola, su pedido está listo" });
});
