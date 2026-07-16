import { contains, mailModels } from "@mail/../tests/mail_test_helpers";
import { registerMailMockRoutes } from "@mail/../tests/mock_server/mail_mock_server";
import { MailTestActivity } from "@test_mail/../tests/mock_server/models/mail_test_activity";
import { MailTestMultiCompany } from "@test_mail/../tests/mock_server/models/mail_test_multi_company";
import { MailTestMultiCompanyRead } from "@test_mail/../tests/mock_server/models/mail_test_multi_company_read";
import { MailTestProperties } from "@test_mail/../tests/mock_server/models/mail_test_properties";
import { MailTestSimple } from "@test_mail/../tests/mock_server/models/mail_test_simple";
import { MailTestTrackAll } from "@test_mail/../tests/mock_server/models/mail_test_track_all";
import { defineModels, defineParams } from "@web/../tests/web_test_helpers";

import { MailTestSimpleMainAttachment } from "./mock_server/models/mail_test_simple_main_attachment.js";

export const testMailModels = {
    ...mailModels,
    MailTestActivity,
    MailTestMultiCompany,
    MailTestMultiCompanyRead,
    MailTestProperties,
    MailTestSimpleMainAttachment,
    MailTestSimple,
    MailTestTrackAll,
};

export function defineTestMailModels() {
    // Bind the mail mock-server routes to the calling test file's suite (see
    // registerMailMockRoutes): without this, every test_mail test runs with
    // NO mail route mocked — no thread data, no messages, no chatter fetch.
    registerMailMockRoutes();
    defineParams({ suite: "test_mail" }, "replace");
    defineModels(testMailModels);
}

export async function editSelect(selector, value) {
    await contains(selector);
    const el = document.querySelector(selector);
    el.value = value;
    el.dispatchEvent(new Event("change"));
}
