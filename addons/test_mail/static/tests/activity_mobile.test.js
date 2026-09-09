import {
    contains,
    openView,
    registerArchs,
    start,
    startServer,
} from "@mail/../tests/mail_test_helpers";
import { beforeEach, describe, test } from "@odoo/hoot";
import { defineTestMailModels } from "@test_mail/../tests/test_mail_test_helpers";

describe.current.tags("mobile");
defineTestMailModels();

const ARCHS = {
    "mail.test.activity,false,activity": `
        <activity string="MailTestActivity">
            <templates>
                <div t-name="activity-box"><field name="name"/></div>
            </templates>
        </activity>`,
};

beforeEach(async () => {
    const pyEnv = await startServer();
    pyEnv["mail.test.activity"].create({ name: "Meeting" });
});

test("the search bar can be revealed on a small screen", async () => {
    // The activity view rendered `<SearchBar/>` with no toggler, so
    // `showSearchBar` defaulted to true and the bar could not be COLLAPSED --
    // it spent control-panel width on a phone where every other view hides it
    // behind this button. `ViewLayout` owns the pair, so the two cannot be
    // wired up half-way.
    await start();
    registerArchs(ARCHS);
    await openView({
        res_model: "mail.test.activity",
        views: [[false, "activity"]],
    });
    await contains("button[aria-label='Toggle the search bar']");
});
