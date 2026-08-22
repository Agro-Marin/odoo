import { UploadDropZone } from "@account/components/upload_drop_zone/upload_drop_zone";
import { describe, expect, test } from "@odoo/hoot";
import { click, queryOne } from "@odoo/hoot-dom";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");

describe("UploadDropZone", () => {
    test("shows while a drag is in flight, with no pointer over it", async () => {
        await mountWithCleanup(UploadDropZone, { props: { dragging: true } });

        expect(".o_drop_area").toHaveCount(1);
        expect(".o_drop_area").not.toHaveClass("drag_to_card");
    });

    test("marks itself as the drop target when the pointer is over it", async () => {
        await mountWithCleanup(UploadDropZone, {
            props: { dragging: true, visible: true },
        });

        expect(".o_drop_area").toHaveClass("drag_to_card");
    });

    test("stays hidden with neither bit set", async () => {
        await mountWithCleanup(UploadDropZone, { props: {} });

        expect(".o_drop_area").toHaveCount(0);
    });

    test("dismisses through hideZone alone, needing nothing from the env", async () => {
        await mountWithCleanup(UploadDropZone, {
            props: { visible: true, hideZone: () => expect.step("hideZone") },
        });

        await click(".o_drop_area");

        expect.verifySteps(["hideZone"]);
    });

    test("hands a drop to the uploader input beside the zone", async () => {
        await mountWithCleanup(UploadDropZone, {
            props: { visible: true, hideZone: () => expect.step("hideZone") },
        });
        const input = document.createElement("input");
        input.type = "file";
        input.className = "document_file_uploader o_input_file";
        input.addEventListener("change", () => expect.step("change"));
        queryOne(".o_drop_area").parentElement.append(input);

        const dataTransfer = new DataTransfer();
        dataTransfer.items.add(
            new File(["x"], "bill.pdf", { type: "application/pdf" }),
        );
        queryOne(".o_drop_area").dispatchEvent(
            new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer }),
        );

        expect(input.files).toHaveLength(1);
        expect.verifySteps(["change", "hideZone"]);
    });
});
