import { startServer } from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import { defineSMSModels } from "@sms/../tests/sms_test_helpers";
import { MockServer, mountView } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");
defineSMSModels();

test("the sms widget renders its counter beside the emoji button, without the placeholder button", async () => {
    await startServer();
    const partnerId = MockServer.env["partner"].create({ message: "Hello there" });
    await mountView({
        type: "form",
        resModel: "partner",
        resId: partnerId,
        arch: `<form><field name="message" widget="sms_widget"/></form>`,
    });
    expect(".o_field_sms_widget textarea").toHaveValue("Hello there");
    expect(".o_field_sms_widget .o_sms_count").toHaveText(/11\/160.*1 SMS \(GSM7\)/);
    expect(
        ".o_field_sms_widget .o_field_input_buttons .o_mail_emojis_buttons",
    ).toHaveCount(1);
    expect(
        ".o_field_sms_widget .o_field_input_buttons .fa-wand-magic-sparkles",
    ).toHaveCount(0);
});
