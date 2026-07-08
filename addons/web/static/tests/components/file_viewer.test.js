// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { click, hover, pointerDown, pointerUp } from "@odoo/hoot-dom";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import { FileViewer } from "@web/components/file_viewer/file_viewer";

describe.current.tags("desktop");

// 1x1 transparent PNG
const IMAGE_SOURCE =
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==";

const IMAGE_FILE = {
    name: "test.png",
    defaultSource: IMAGE_SOURCE,
    downloadUrl: "/web/content/1?download=true",
    isImage: true,
    isViewable: true,
};

const TEXT_FILE = {
    name: "test.txt",
    defaultSource: "about:blank",
    downloadUrl: "/web/content/2?download=true",
    isText: true,
    isViewable: true,
};

test("releasing an image pan outside the image does not close the viewer", async () => {
    const viewer = await mountWithCleanup(FileViewer, {
        props: {
            files: [IMAGE_FILE],
            startIndex: 0,
            close: () => expect.step("close"),
        },
    });

    await pointerDown(".o-FileViewer-viewImage");
    expect(viewer.isDragging).toBe(true);

    // Pan: the pointer moves off the image, over the main view.
    await hover(".o-FileViewer-main", { position: { x: 5, y: 5 } });
    expect(viewer.didDrag).toBe(true);

    // Releasing the pointer outside the image must end the pan, and the
    // composed click on the main view must not close the viewer.
    await pointerUp(".o-FileViewer-main");
    expect(viewer.isDragging).toBe(false);
    expect.verifySteps([]);

    // Panning stopped: further pointer moves must not translate the image.
    await hover(".o-FileViewer-main", { position: { x: 60, y: 60 } });
    expect(viewer.translate.dx).toBe(0);
    expect(viewer.translate.dy).toBe(0);

    // A genuine click on the backdrop still closes the viewer.
    await click(".o-FileViewer-main");
    expect.verifySteps(["close"]);
});

test("switching file resets the iframe loaded state", async () => {
    const viewer = await mountWithCleanup(FileViewer, {
        props: {
            files: [TEXT_FILE, IMAGE_FILE],
            startIndex: 0,
            close: () => {},
        },
    });

    viewer.state.isIframeLoaded = true;
    await click(".o-FileViewer-navigation[aria-label='Next']");
    expect(viewer.state.isIframeLoaded).toBe(false);
    expect(viewer.state.index).toBe(1);
});
