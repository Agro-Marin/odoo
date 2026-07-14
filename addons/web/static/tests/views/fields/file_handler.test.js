// @ts-check

import { expect, test } from "@odoo/hoot";
import { queryOne, setInputFiles } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { Component, xml } from "@odoo/owl";
import {
    contains,
    mockService,
    mountWithCleanup,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { FileUploader } from "@web/core/file_upload/file_handler";
import { session } from "@web/session";

/**
 * Minimal host exposing a toggler so the hidden file input is "interacted with"
 * the same way the real widgets drive it (button -> onSelectFileButtonClick ->
 * input.click()), which is what `setInputFiles` needs.
 */
class Parent extends Component {
    static components = { FileUploader };
    static template = xml`
        <FileUploader
            onUploaded="props.onUploaded"
            onUploadComplete="props.onUploadComplete"
            multiUpload="props.multiUpload"
            checkSize="props.checkSize"
            allowedMIMETypes="props.allowedMIMETypes">
            <t t-set-slot="toggler">
                <button class="o_test_toggler">Upload</button>
            </t>
        </FileUploader>
    `;
    static props = ["*"];
}

test("FileUploader accepts only an exact allowed MIME and rejects empty type", async () => {
    const notifications = [];
    mockService("notification", { add: (message) => notifications.push(message) });
    const uploaded = [];
    await mountWithCleanup(Parent, {
        props: {
            allowedMIMETypes: "application/pdf",
            onUploaded: (file) => uploaded.push(file.name),
        },
    });

    // Exact match: accepted.
    await contains(".o_test_toggler").click();
    await setInputFiles([new File(["%PDF-"], "ok.pdf", { type: "application/pdf" })]);
    await animationFrame();
    expect(uploaded).toEqual(["ok.pdf"]);
    expect(notifications).toHaveLength(0);

    // Substring of the allowed type ("pdf" ⊂ "application/pdf"): rejected.
    await contains(".o_test_toggler").click();
    await setInputFiles([new File(["x"], "sub.pdf", { type: "pdf" })]);
    await animationFrame();
    expect(uploaded).toEqual(["ok.pdf"]);
    expect(notifications).toHaveLength(1);

    // Empty MIME type (was previously accepted by `includes("")`): rejected.
    await contains(".o_test_toggler").click();
    await setInputFiles([new File(["x"], "unknown.bin", { type: "" })]);
    await animationFrame();
    expect(uploaded).toEqual(["ok.pdf"]);
    expect(notifications).toHaveLength(2);
});

test("FileUploader multi-upload continues past a too-large file and resets input", async () => {
    patchWithCleanup(session, { max_file_upload_size: 3 });
    mockService("notification", { add: () => {} });
    const uploaded = [];
    await mountWithCleanup(Parent, {
        props: {
            multiUpload: true,
            checkSize: true,
            onUploaded: (file) => uploaded.push(file.name),
        },
    });

    await contains(".o_test_toggler").click();
    await setInputFiles([
        new File(["ab"], "small_1.txt", { type: "text/plain" }), // 2 bytes: ok
        new File(["way-too-big"], "big.txt", { type: "text/plain" }), // >3 bytes: skipped
        new File(["cd"], "small_2.txt", { type: "text/plain" }), // 2 bytes: ok
    ]);
    await animationFrame();

    // The oversized file is skipped but the remaining files still upload.
    expect(uploaded).toEqual(["small_1.txt", "small_2.txt"]);
    // Input is cleared so re-selecting the same file fires "change" again.
    expect(queryOne(".o_input_file").value).toBe("");
});
