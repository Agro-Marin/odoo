import {
    contains,
    defineMailModels,
    onRpcBefore,
    start,
} from "@mail/../tests/mail_test_helpers";
import { describe, test } from "@odoo/hoot";
import { getService, makeServerError } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");
defineMailModels();

test("a channel redirect whose thread fetch fails notifies instead of hanging", async () => {
    onRpcBefore("/mail/data", (args) => {
        const isProbe = args.fetch_params.some(
            (param) =>
                Array.isArray(param) &&
                param[0] === "mixin.mail.thread" &&
                param[1]?.thread_id === 4242,
        );
        if (isProbe) {
            throw makeServerError({ message: "fetch boom" });
        }
    });
    await start();
    getService("mail.link_navigation").openRedirectedThread("res.partner", 4242);
    await contains(".o_notification:has(.o_notification_bar.bg-danger)", {
        text: "This thread is no longer available.",
    });
});
