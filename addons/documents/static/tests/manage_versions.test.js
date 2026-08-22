import { DocumentsManageVersions } from "@documents/components/documents_manage_versions_panel/documents_manage_versions_panel";
import { describe, expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { EventBus } from "@odoo/owl";
import {
    defineModels,
    getService,
    mockService,
    mountWithCleanup,
    onRpc,
} from "@web/../tests/web_test_helpers";
import { MainComponentsContainer } from "@web/ui/main_components_container";

import { DocumentsModels } from "./helpers/data.js";
import { makeDocumentsMockEnv } from "./helpers/model.js";

describe.current.tags("desktop");

defineModels(DocumentsModels);

const DOCUMENT_ID = 7;

/**
 * @returns {Promise<{bus: EventBus, reads: number[]}>}
 */
async function mountPanel() {
    const bus = new EventBus();
    const reads = [];
    mockService("file_upload", { bus, upload: () => {} });
    onRpc("documents.document", "web_read", ({ args }) => {
        reads.push(args[0]);
        return [
            {
                id: DOCUMENT_ID,
                name: "Contract",
                access_token: "tok",
                user_permission: "edit",
                attachment_id: {
                    id: 1,
                    name: "v2",
                    mimetype: "application/pdf",
                    create_date: "2026-07-24 10:00:00",
                    create_uid: { id: 2, name: "Mitchell Admin" },
                },
                previous_attachment_ids: [],
            },
        ];
    });
    await makeDocumentsMockEnv();
    await mountWithCleanup(MainComponentsContainer);
    getService("dialog").add(DocumentsManageVersions, { documentId: DOCUMENT_ID });
    await animationFrame();
    await animationFrame();
    return { bus, reads };
}

/**
 * @param {EventBus} bus
 * @param {number|undefined} documentId
 */
function fireUploadLoaded(bus, documentId) {
    const data = new FormData();
    if (documentId !== undefined) {
        data.append("document_id", String(documentId));
    }
    bus.trigger("FILE_UPLOAD_LOADED", {
        upload: { data, xhr: { status: 200, response: "[1]" } },
    });
}

test("reloads when this document's own new version lands", async () => {
    const { bus, reads } = await mountPanel();
    const initial = reads.length;
    expect(initial).toBeGreaterThan(0, {
        message: "the panel read the history on mount",
    });

    fireUploadLoaded(bus, DOCUMENT_ID);
    await animationFrame();

    expect(reads.length).toBe(initial + 1);
});

test("ignores an upload belonging to another document", async () => {
    const { bus, reads } = await mountPanel();
    const initial = reads.length;

    fireUploadLoaded(bus, DOCUMENT_ID + 1);
    await animationFrame();

    expect(reads.length).toBe(initial, {
        message: "another document's new version does not re-read this history",
    });
});

test("ignores an upload that is not a version replacement at all", async () => {
    const { bus, reads } = await mountPanel();
    const initial = reads.length;

    fireUploadLoaded(bus, undefined);
    await animationFrame();

    expect(reads.length).toBe(initial);
});
