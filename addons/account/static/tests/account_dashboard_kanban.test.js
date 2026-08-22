import { openKanbanView, start, startServer } from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import { animationFrame, queryOne } from "@odoo/hoot-dom";
import { contains, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { user } from "@web/core/user";

import { defineAccountModels } from "./account_test_helpers.js";

describe.current.tags("desktop");
defineAccountModels();

const DROP_GROUP = "account.group_account_user";

const ARCH = `
    <kanban js_class="account_dashboard_kanban">
        <field name="kanban_dashboard"/>
        <templates>
            <t t-name="card"><field name="name"/></t>
        </templates>
    </kanban>`;

/** @param {Object} [dragDropSettings] extra keys for the `drag_drop_settings` blob */
function dashboardBlob(dragDropSettings) {
    return JSON.stringify({
        company_name: "Test Company",
        show_company: false,
        drag_drop_settings: {
            image: "/account/static/src/img/folder.svg",
            text: "Drop to create journal entries with attachments.",
            ...dragDropSettings,
        },
    });
}

/**
 * Step only the membership question under test: the kanban asks about unrelated
 * groups (export rights) whose number is not this test's business.
 *
 * @param {boolean} isMember
 */
function mockDropGroup(isMember) {
    patchWithCleanup(user, {
        async hasGroup(group) {
            if (group === DROP_GROUP) {
                expect.step(`hasGroup:${group}`);
                return isMember;
            }
            return super.hasGroup(group);
        },
    });
}

/**
 * `_fill_general_dashboard_data` gates the drop-to-upload affordance on a group.
 * The card must honour it: the point of sending the group is that a user outside
 * it never gets the uploader.
 */
describe("dashboard drop group", () => {
    test("hides the uploader when the user is not in drag_drop_settings.group", async () => {
        const pyEnv = await startServer();
        pyEnv["account.journal"].create({
            name: "Miscellaneous",
            type: "general",
            kanban_dashboard: dashboardBlob({ group: DROP_GROUP }),
        });
        await start();
        mockDropGroup(false);

        await openKanbanView("account.journal", { arch: ARCH });

        expect.verifySteps([`hasGroup:${DROP_GROUP}`]);
        expect(".document_file_uploader").toHaveCount(0);
    });

    test("shows the uploader when the user is in drag_drop_settings.group", async () => {
        const pyEnv = await startServer();
        pyEnv["account.journal"].create({
            name: "Miscellaneous",
            type: "general",
            kanban_dashboard: dashboardBlob({ group: DROP_GROUP }),
        });
        await start();
        mockDropGroup(true);

        await openKanbanView("account.journal", { arch: ARCH });

        expect.verifySteps([`hasGroup:${DROP_GROUP}`]);
        expect(".document_file_uploader").toHaveCount(1);
    });

    test("dismissing a card's dropzone clears the renderer-wide drag state too", async () => {
        const pyEnv = await startServer();
        pyEnv["account.journal"].create({
            name: "Vendor Bills",
            type: "purchase",
            kanban_dashboard: dashboardBlob(),
        });
        await start();
        mockDropGroup(false);

        await openKanbanView("account.journal", { arch: ARCH });

        // Both bits gate the zone: the renderer's "a drag is in flight" and the
        // card's "the pointer is over me". Clearing one alone left it up.
        const record = queryOne(".o_kanban_record:not(.o_kanban_ghost)");
        record.dispatchEvent(
            new DragEvent("dragenter", { bubbles: true, cancelable: true }),
        );
        await animationFrame();
        expect(".o_drop_area").toHaveCount(1);

        await contains(".o_drop_area").click();

        expect(".o_drop_area").toHaveCount(0);
    });

    test("shows the uploader when no group gates it", async () => {
        const pyEnv = await startServer();
        pyEnv["account.journal"].create({
            name: "Vendor Bills",
            type: "purchase",
            kanban_dashboard: dashboardBlob(),
        });
        await start();
        mockDropGroup(false);

        await openKanbanView("account.journal", { arch: ARCH });

        // No group in the blob: no membership question is asked at all.
        expect.verifySteps([]);
        expect(".document_file_uploader").toHaveCount(1);
    });
});
