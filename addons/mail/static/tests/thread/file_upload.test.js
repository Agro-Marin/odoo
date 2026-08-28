import {
    click,
    contains,
    defineMailModels,
    inputFiles,
    openDiscuss,
    openFormView,
    start,
    startServer,
} from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import { Deferred } from "@odoo/hoot-mock";
import { getService, onRpc } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");
defineMailModels();

test("no conflicts between file uploads", async () => {
    const pyEnv = await startServer();
    const partnerId = pyEnv["res.partner"].create({});
    const channelId = pyEnv["discuss.channel"].create({});
    const text = new File(["hello, world"], "text1.txt", { type: "text/plain" });
    const text2 = new File(["hello, world"], "text2.txt", { type: "text/plain" });
    pyEnv["mail.message"].create({
        body: "not empty",
        model: "discuss.channel",
        res_id: channelId,
    });
    await start();
    await openFormView("res.partner", partnerId);
    await click("button", { text: "Send message" });
    await inputFiles(".o-mail-Chatter .o-mail-Composer input[type=file]", [text]);
    await click("i[aria-label='Messages']");
    await click(".o-mail-NotificationItem");
    await inputFiles(".o-mail-ChatWindow .o-mail-Composer input[type=file]", [text2]);
    await contains(".o-mail-Chatter .o-mail-AttachmentContainer");
    await contains(".o-mail-ChatWindow .o-mail-AttachmentContainer");
    await contains(
        ".o-mail-Chatter .o-mail-AttachmentContainer:not(.o-isUploading):contains(text1.txt)",
    );
    await contains(
        ".o-mail-ChatWindow .o-mail-AttachmentContainer:not(.o-isUploading):contains(text2.txt)",
    );
});

test("Attachment shows spinner during upload", async () => {
    const pyEnv = await startServer();
    const channelId = pyEnv["discuss.channel"].create({ name: "channel_1" });
    const text2 = new File(["hello, world"], "text2.txt", { type: "text/plain" });
    onRpc("/mail/attachment/upload", () => new Deferred());
    await start();
    await openDiscuss(channelId);
    await inputFiles(".o-mail-Composer input[type=file]", [text2]);
    await contains(
        ".o-mail-AttachmentContainer.o-isUploading:contains(text2.txt) .fa-circle-notch",
    );
});

/**
 * Drives a real upload that never resolves, so the service holds genuine
 * in-flight state, then hands it the transport result the test wants to pin.
 * Faking the whole upload instead would assert against the fake.
 * @param {number} status
 * @param {string} [response]
 */
async function uploadThenRespond(status, response) {
    const pyEnv = await startServer();
    const channelId = pyEnv["discuss.channel"].create({ name: "channel_1" });
    const file = new File(["hello, world"], "text.txt", { type: "text/plain" });
    onRpc("/mail/attachment/upload", () => new Deferred());
    await start();
    await openDiscuss(channelId);
    await inputFiles(".o-mail-Composer input[type=file]", [file]);
    await contains(".o-mail-AttachmentContainer.o-isUploading:contains(text.txt)");

    const service = getService("mail.attachment_upload");
    const [tmpId] = [...service.uploadingAttachmentIds];
    const data = new FormData();
    data.append("temporary_id", String(tmpId));
    getService("file_upload").bus.dispatchEvent(
        new CustomEvent("FILE_UPLOAD_LOADED", {
            detail: { upload: { data, xhr: { status, response } } },
        }),
    );
    return { service, tmpId };
}

test("an upload refused as too large is reported and stops uploading", async () => {
    const { service, tmpId } = await uploadThenRespond(413);
    await contains(".o_notification", { text: "File too large" });
    await contains(".o-mail-AttachmentContainer.o-isUploading", { count: 0 });
    expect(service.uploadingAttachmentIds.has(tmpId)).toBe(false);
});

test("an upload answered with a server error is reported and stops uploading", async () => {
    const { service, tmpId } = await uploadThenRespond(500);
    await contains(".o_notification", { text: "Server error" });
    expect(service.uploadingAttachmentIds.has(tmpId)).toBe(false);
});

test("an upload answered with unparsable content is reported as a server error", async () => {
    const { service, tmpId } = await uploadThenRespond(200, "<html>not json</html>");
    await contains(".o_notification", { text: "Server error" });
    expect(service.uploadingAttachmentIds.has(tmpId)).toBe(false);
});

test("an upload whose response carries an error reports that error verbatim", async () => {
    const { service, tmpId } = await uploadThenRespond(
        200,
        JSON.stringify({ error: "You are not allowed to upload here" }),
    );
    await contains(".o_notification", { text: "You are not allowed to upload here" });
    expect(service.uploadingAttachmentIds.has(tmpId)).toBe(false);
});

test("a transport-level upload failure stops uploading without a notification", async () => {
    const pyEnv = await startServer();
    const channelId = pyEnv["discuss.channel"].create({ name: "channel_1" });
    const file = new File(["hello, world"], "text.txt", { type: "text/plain" });
    onRpc("/mail/attachment/upload", () => new Deferred());
    await start();
    await openDiscuss(channelId);
    await inputFiles(".o-mail-Composer input[type=file]", [file]);
    await contains(".o-mail-AttachmentContainer.o-isUploading:contains(text.txt)");

    const service = getService("mail.attachment_upload");
    const [tmpId] = [...service.uploadingAttachmentIds];
    const data = new FormData();
    data.append("temporary_id", String(tmpId));
    getService("file_upload").bus.dispatchEvent(
        new CustomEvent("FILE_UPLOAD_ERROR", { detail: { upload: { data } } }),
    );
    await contains(".o-mail-AttachmentContainer.o-isUploading", { count: 0 });
    expect(service.uploadingAttachmentIds.has(tmpId)).toBe(false);
    await contains(".o_notification", { count: 0 });
});
