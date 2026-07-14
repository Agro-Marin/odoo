import { click, contains, openFormView, start, startServer } from "@mail/../tests/mail_test_helpers";
import { describe, test } from "@odoo/hoot";
import { getService } from "@web/../tests/web_test_helpers";

import { defineProjectModels } from "./project_models.js";

defineProjectModels();
describe.current.tags("desktop");

async function openThreadWithFollower({ collaborator }) {
    const pyEnv = await startServer();
    const [threadId, partnerId] = pyEnv["res.partner"].create([
        { name: "Thread record" },
        { name: "Follower partner" },
    ]);
    pyEnv["mail.followers"].create({
        is_active: true,
        partner_id: partnerId,
        res_id: threadId,
        res_model: "res.partner",
    });
    await start();
    await openFormView("res.partner", threadId);
    if (collaborator) {
        // The server only serializes collaborator_ids for project threads
        // (project.project._thread_to_store); seed the store directly to
        // exercise the follower-side logic.
        const thread = getService("mail.store").Thread.insert({
            model: "res.partner",
            id: threadId,
        });
        thread.collaborator_ids = [{ id: partnerId }];
    }
    await click(".o-mail-Followers-button");
    await contains(".o-mail-Follower");
}

test("removing a collaborator follower asks for confirmation", async () => {
    await openThreadWithFollower({ collaborator: true });
    await click("[title='Remove this follower']");
    await contains(".modal", { text: "Remove Collaborator" });
    // Discard keeps the follower subscribed.
    await click(".modal button", { text: "Discard" });
    await contains(".modal", { count: 0 });
    await click(".o-mail-Followers-button");
    await contains(".o-mail-Follower");
    // Confirm actually removes them.
    await click("[title='Remove this follower']");
    await click(".modal button", { text: "Remove Collaborator" });
    await contains(".o-mail-Follower", { count: 0 });
});

test("removing a regular follower does not ask for confirmation", async () => {
    await openThreadWithFollower({ collaborator: false });
    await click("[title='Remove this follower']");
    await contains(".modal", { count: 0 });
    await contains(".o-mail-Follower", { count: 0 });
});
