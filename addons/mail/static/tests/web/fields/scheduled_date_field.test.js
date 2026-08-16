import {
    click,
    contains,
    defineMailModels,
    openView,
    registerArchs,
    start,
    startServer,
} from "@mail/../tests/mail_test_helpers";
import { beforeEach, test } from "@odoo/hoot";
import { mockDate } from "@odoo/hoot-mock";

import { MailComposeMessage } from "../../mock_server/mock_models/mail_composer_message.js";

defineMailModels();
beforeEach(() => mockDate("2024-10-20 10:00:00", +1));

test("Text scheduled date field", async () => {
    const pyEnv = await startServer();
    MailComposeMessage._views = {
        "form,false": `<form><field name="scheduled_date" widget="text_scheduled_date"/></form>`,
    };
    const composerId = pyEnv["mail.compose.message"].create({
        subject: "Greetings",
        body: "<p>Hello There</p>",
        model: "res.partner",
    });
    await start();
    await openView({
        res_model: "mail.compose.message",
        res_id: composerId,
        views: [["mail.compose.message,false,form", "form"]],
    });
    await contains(".o_field_text_scheduled_date button", { text: "" });
    await click(".o_field_text_scheduled_date button");
    await contains(".modal");
    await contains(".modal-footer button", { text: "Clear Time", count: 0 });
    await click(".modal input[value='afternoon']");
    await contains(".modal input[value='afternoon']:checked");
    await click(".modal-footer .btn-primary");
    await contains(".o_field_text_scheduled_date button", {
        text: "Sending Oct 21, 1:00 PM",
    });
    await click(".o_field_text_scheduled_date button");
    await contains(".modal input[value='afternoon']:checked");
    await click(".modal-footer button:contains('Clear Time')");
    await contains(".o_field_text_scheduled_date button", { text: "" });
});

test("Datetime scheduled date field", async () => {
    const pyEnv = await startServer();
    registerArchs({
        "mail.scheduled.message,false,form": `<form><field name="scheduled_date" widget="datetime_scheduled_date"/></form>`,
    });
    const composerId = pyEnv["mail.scheduled.message"].create({
        subject: "Greetings",
        body: "<p>Hello There</p>",
        model: "res.partner",
        scheduled_date: "2024-10-21 12:00:00",
    });
    await start();
    await openView({
        res_model: "mail.scheduled.message",
        res_id: composerId,
        views: [["mail.scheduled.message,false,form", "form"]],
    });
    await contains(".o_field_datetime_scheduled_date button", {
        text: "Sending Oct 21, 1:00 PM",
    });
    await click(".o_field_datetime_scheduled_date button");
    await contains(".modal");
    await contains(".modal input[value='afternoon']:checked");
    await contains(".modal-footer button", { text: "Clear Time", count: 0 });
    await click(".modal input[value='morning']");
    await contains(".modal input[value='morning']:checked");

    await click(".modal-footer .btn-primary");

    await contains(".o_field_datetime_scheduled_date button", {
        text: "Sending Oct 21, 8:00 AM",
    });
});
