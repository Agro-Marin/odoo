import { defineMailModels, start } from "@mail/../tests/mail_test_helpers";
import { IM_STATUS_DEBOUNCE_DELAY } from "@mail/core/common/constants";
import { MailGuest } from "@mail/core/common/mail_guest_model";
import { ResPartner } from "@mail/core/common/res_partner_model";
import { describe, expect, test } from "@odoo/hoot";
import { advanceTime } from "@odoo/hoot-mock";
import { getService, patchWithCleanup } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");
defineMailModels();

for (const [label, Model, modelName] of [
    ["partner", ResPartner, "res.partner"],
    ["guest", MailGuest, "mail.guest"],
]) {
    test(`deleting a ${label} cancels its pending im_status update`, async () => {
        await start();
        const store = getService("mail.store");
        patchWithCleanup(Model.prototype, {
            updateImStatus(newStatus) {
                expect.step(`${this.id}:${newStatus}`);
                return super.updateImStatus(newStatus);
            },
        });
        const gone = store[modelName].insert({ id: 4242, name: "Gone" });
        const alive = store[modelName].insert({ id: 4243, name: "Alive" });
        gone.debouncedSetImStatus("online");
        alive.debouncedSetImStatus("online");
        gone.delete();
        await advanceTime(IM_STATUS_DEBOUNCE_DELAY + 1);
        expect.verifySteps(["4243:online"]);
        expect(alive.im_status).toBe("online");
        expect(gone.exists()).toBe(false);
    });
}
