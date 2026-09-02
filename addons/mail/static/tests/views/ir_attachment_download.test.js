import { defineMailModels, startServer } from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import { queryAllTexts } from "@odoo/hoot-dom";
import {
    asyncStep,
    contains,
    mountView,
    patchWithCleanup,
    waitForSteps,
} from "@web/../tests/web_test_helpers";
import { download } from "@web/core/network/download";

describe.current.tags("desktop");
defineMailModels();

const LIST_ARCH = `
    <list js_class="ir_attachment_list">
        <field name="name"/>
        <field name="type"/>
    </list>`;

/**
 * Mount the attachment list the way the technical menu shows it. `actionMenus`
 * has to be passed for the cog to be built at all: mounted without it, the
 * control panel offers no action items, static ones included.
 */
async function mountAttachmentList() {
    return mountView({
        actionMenus: {},
        arch: LIST_ARCH,
        resModel: "ir.attachment",
        type: "list",
    });
}

/** @returns {{ firstId: number, secondId: number }} */
function seedAttachments(pyEnv) {
    const [firstId, secondId] = pyEnv["ir.attachment"].create([
        { mimetype: "text/plain", name: "first.txt", type: "binary" },
        { mimetype: "text/plain", name: "second.txt", type: "binary" },
    ]);
    pyEnv["ir.attachment"].create({
        name: "a link",
        type: "url",
        url: "https://example.com",
    });
    return { firstId, secondId };
}

test("several selected attachments download as one zip", async () => {
    const { firstId, secondId } = seedAttachments(await startServer());
    patchWithCleanup(download, {
        _download: (options) => {
            asyncStep(`${options.url}:${options.data.file_ids}`);
            return Promise.resolve();
        },
    });
    await mountAttachmentList();
    await contains(".o_data_row:eq(0) .o_list_record_selector input").click();
    await contains(".o_data_row:eq(1) .o_list_record_selector input").click();
    await contains(".o_cp_action_menus .dropdown-toggle").click();
    await contains(".o-dropdown-item:contains('Download')").click();
    await waitForSteps([`/mail/attachment/zip:${firstId},${secondId}`]);
});

test("a single selected attachment downloads as itself", async () => {
    const { firstId } = seedAttachments(await startServer());
    patchWithCleanup(download, {
        _download: (options) => {
            asyncStep(`${options.url}:${options.data.id}`);
            return Promise.resolve();
        },
    });
    await mountAttachmentList();
    await contains(".o_data_row:eq(0) .o_list_record_selector input").click();
    await contains(".o_cp_action_menus .dropdown-toggle").click();
    await contains(".o-dropdown-item:contains('Download')").click();
    await waitForSteps([`/web/content:${firstId}`]);
});

test("a url attachment has no file to download, so the action is not offered", async () => {
    seedAttachments(await startServer());
    await mountAttachmentList();
    await contains(".o_data_row:eq(2) .o_list_record_selector input").click();
    await contains(".o_cp_action_menus .dropdown-toggle").click();
    expect(queryAllTexts(".o-dropdown-item")).not.toInclude("Download");
});
