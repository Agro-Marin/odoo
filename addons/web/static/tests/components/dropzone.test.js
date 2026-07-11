// @ts-check

import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { Component, useRef, useState, xml } from "@odoo/owl";
import { dragenterFiles, dropFiles } from "@web/../tests/utils";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import { useDropzone } from "@web/components/dropzone/dropzone_hook";

class Host extends Component {
    static template = xml`<div class="test-dropzone-host" t-ref="root">host</div>`;
    static props = ["*"];
    setup() {
        useDropzone(useRef("root"), () => expect.step("drop"));
    }
}

test("dropzone overlay appears while dragging files and handles the drop", async () => {
    await mountWithCleanup(Host);
    expect(".o-Dropzone").toHaveCount(0);

    const files = [new File(["hello"], "hello.txt", { type: "text/plain" })];
    await dragenterFiles(".test-dropzone-host", files);
    // The overlay is added through the overlay service: its container renders
    // on the next animation frame.
    await animationFrame();
    expect(".o-Dropzone").toHaveCount(1);

    await dropFiles(".o-Dropzone", files);
    await animationFrame();
    expect.verifySteps(["drop"]);
    expect(".o-Dropzone").toHaveCount(0);
});

test("dropzone overlay is removed when its owner is destroyed mid-drag", async () => {
    class Parent extends Component {
        static components = { Host };
        static template = xml`<Host t-if="state.show"/>`;
        static props = ["*"];
        setup() {
            this.state = useState({ show: true });
        }
    }
    const parent = await mountWithCleanup(Parent);

    const files = [new File(["hello"], "hello.txt", { type: "text/plain" })];
    await dragenterFiles(".test-dropzone-host", files);
    await animationFrame();
    expect(".o-Dropzone").toHaveCount(1);

    parent.state.show = false;
    // Teardown is two-staged: the first frame re-renders the parent and
    // unmounts the host (its `onWillDestroy` asks the overlay service to drop
    // the dropzone), the second frame re-renders the overlay container.
    await animationFrame();
    await animationFrame();
    expect(".o-Dropzone").toHaveCount(0);
});
