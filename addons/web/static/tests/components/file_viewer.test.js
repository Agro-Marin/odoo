// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { animationFrame, click, hover, pointerDown, pointerUp } from "@odoo/hoot-dom";
import { Component, useState, xml } from "@odoo/owl";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import { FileModel } from "@web/components/file_viewer/file_model";
import { FileViewer } from "@web/components/file_viewer/file_viewer";

describe.current.tags("desktop");

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

    await hover(".o-FileViewer-main", { position: { x: 5, y: 5 } });
    expect(viewer.didDrag).toBe(true);

    await pointerUp(".o-FileViewer-main");
    expect(viewer.isDragging).toBe(false);
    expect.verifySteps([]);

    await hover(".o-FileViewer-main", { position: { x: 60, y: 60 } });
    expect(viewer.translate.dx).toBe(0);
    expect(viewer.translate.dy).toBe(0);

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

test("re-anchors on a new files list", async () => {
    const other = { ...IMAGE_FILE, name: "other.png" };
    let update;
    class Parent extends Component {
        static components = { FileViewer };
        static props = {};
        static template = xml`<FileViewer files="state.files" startIndex="0" modal="false"/>`;
        setup() {
            this.state = useState({ files: [IMAGE_FILE, other] });
            update = (files) => (this.state.files = files);
        }
    }
    await mountWithCleanup(Parent);
    expect(".o-FileViewer-header .text-truncate").toHaveText("test.png");

    // Reordering keeps the viewed file, not the index.
    update([other, IMAGE_FILE]);
    await animationFrame();
    expect(".o-FileViewer-header .text-truncate").toHaveText("test.png");

    // Removing the viewed file falls back within the new list.
    update([other]);
    await animationFrame();
    expect(".o-FileViewer-header .text-truncate").toHaveText("other.png");

    // Emptying the list renders nothing instead of a stale preview.
    update([]);
    await animationFrame();
    expect(".o-FileViewer").toHaveCount(0);
});

test("re-anchors on a plain (non-reactive) files list", async () => {
    const other = { ...IMAGE_FILE, name: "other.png" };
    let reorder;
    class Parent extends Component {
        static components = { FileViewer };
        static props = {};
        static template = xml`<FileViewer files="files" startIndex="0" modal="false"/>`;
        setup() {
            this.state = useState({ flipped: false });
            this.rawFiles = [IMAGE_FILE, other];
            reorder = () => {
                this.rawFiles = [other, IMAGE_FILE];
                this.state.flipped = true;
            };
        }
        get files() {
            return this.rawFiles;
        }
    }
    await mountWithCleanup(Parent);
    expect(".o-FileViewer-header .text-truncate").toHaveText("test.png");

    reorder();
    await animationFrame();
    expect(".o-FileViewer-header .text-truncate").toHaveText("test.png");
});

test("youtube URLs are matched on the host, not on a substring", async () => {
    const videoId = (url) =>
        Object.assign(new FileModel(), { type: "url", url }).youtubeVideoId;

    expect([
        videoId("https://www.youtube.com/watch?v=abc123"),
        videoId("https://youtube.com/watch?app=desktop&v=abc123&t=30"),
        videoId("https://youtu.be/abc123"),
        videoId("https://youtu.be/abc123?t=30"),
        videoId("https://www.youtube.com/embed/abc123"),
        videoId("https://www.youtube.com/shorts/abc123"),
        videoId("https://www.youtube-nocookie.com/embed/abc123"),
    ]).toEqual(Array(7).fill("abc123"));

    // A link that merely contains "youtu" must stay a plain URL.
    const impostor = Object.assign(new FileModel(), {
        type: "url",
        url: "https://example.com/my-youtube-clone/page",
    });
    expect(impostor.isUrlYoutube).toBe(false);
    expect(impostor.defaultSource).not.toInclude("youtube.com/embed");

    // Subdomain spoofing must not pass either.
    expect(videoId("https://youtube.evil.com/watch?v=abc123")).toBe(null);
});

test("dragging an image measures the layout once per frame, not once per event", async () => {
    let measures = 0;
    class Probe extends FileViewer {
        updateZoomerStyle() {
            measures++;
            return super.updateZoomerStyle();
        }
    }
    const viewer = await mountWithCleanup(Probe, {
        props: { files: [IMAGE_FILE], startIndex: 0, modal: false },
    });
    await animationFrame();
    // Zoom in so the image overflows its zoomer and the translation is applied.
    viewer.zoomIn();
    viewer.zoomIn();
    await animationFrame();

    measures = 0;
    await pointerDown(".o-FileViewer-viewImage", { position: { x: 0, y: 0 } });
    for (let i = 1; i <= 20; i++) {
        await hover(".o-FileViewer-main", { position: { x: i * 3, y: i * 2 } });
    }
    // 20 pointermoves used to mean 20 forced layouts.
    expect(measures).toBeLessThan(20);
    // Throttling the style write must not lose the last move.
    expect(viewer.translate.dx).toBe(60);
    expect(viewer.translate.dy).toBe(40);

    // The drop is not deferred: it settles the offset straight away.
    const beforeDrop = measures;
    await pointerUp(".o-FileViewer-main");
    expect(measures).toBeGreaterThan(beforeDrop);
    expect(viewer.translate.dx).toBe(0);
    expect(viewer.translate.dy).toBe(0);
});
