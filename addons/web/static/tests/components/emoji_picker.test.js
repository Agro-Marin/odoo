// @ts-check

import { expect, test } from "@odoo/hoot";
import { click, waitFor } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { Component, useRef, useState, xml } from "@odoo/owl";
import { mountWithCleanup, patchWithCleanup } from "@web/../tests/web_test_helpers";
import {
    EmojiPicker,
    loader,
    useEmojiPicker,
} from "@web/components/emoji_picker/emoji_picker";
import { browser } from "@web/core/browser/browser";

// No `preloadBundle("web.assets_emoji")`: that path fetches the real ~530 KB
// bundle over the network (it runs under `withFetch(globalCachedFetch)`, which
// bypasses the mock server). The mock server now serves a lightweight emoji
// stub for `web.assets_emoji`, so the picker's own `onWillStart` load is
// instant and needs no preload.

test("frequent emojis with unknown codepoints do not crash the picker", async () => {
    // Simulate a stale localStorage entry with codepoints no longer in the current bundle.
    browser.localStorage.setItem(
        "web.emoji.frequent",
        JSON.stringify({ "<removed codepoints>": 5, "😀": 2 }),
    );
    await mountWithCleanup(EmojiPicker, { props: { onSelect: () => {} } });
    expect(".o-EmojiPicker").toHaveCount(1);
    // Only the emoji still present in the data shows up in "Frequently used" (sortId 0).
    expect(".o-EmojiPicker-content .o-Emoji[data-category='0']").toHaveCount(1);
    expect(".o-EmojiPicker-content .o-Emoji[data-category='0']").toHaveText("😀");
});

test("fallback UI is displayed when the emoji bundle fails to load", async () => {
    patchWithCleanup(loader, {
        loadEmoji: () => Promise.reject(new Error("bundle load failure")),
    });
    await mountWithCleanup(EmojiPicker, { props: { onSelect: () => {} } });
    expect(".o-EmojiPicker").toHaveCount(1);
    expect(".o-EmojiPicker span.text-muted").toHaveText("Failed to load emojis...");
    expect(".o-EmojiPicker input").toHaveCount(0);
});

test.tags("mobile");
test("mobile picker dialog is torn down with its owner", async () => {
    let picker;
    class Host extends Component {
        static template = xml`<div class="test-host"/>`;
        static props = ["*"];
        setup() {
            picker = useEmojiPicker(null, {
                onSelect: () => {},
                onClose: () => expect.step("closed"),
            });
        }
    }
    class Parent extends Component {
        static components = { Host };
        static template = xml`<Host t-if="state.show"/>`;
        static props = ["*"];
        setup() {
            this.state = useState({ show: true });
        }
    }
    const parent = await mountWithCleanup(Parent);

    picker.open();
    await waitFor(".modal .o-EmojiPicker");

    parent.state.show = false;
    // Two frames: the emoji data now loads asynchronously (mock stub, no
    // synchronous preload), so the picker's teardown settles one render cycle
    // after the owner's — the first frame unmounts the owner, the second
    // flushes the dialog removal.
    await animationFrame();
    await animationFrame();
    expect(".modal").toHaveCount(0);
    expect(".o-EmojiPicker").toHaveCount(0);
    expect.verifySteps(["closed"]);
});

test.tags("mobile");
test("mobile picker app is torn down with its owner", async () => {
    class Host extends Component {
        static template = xml`<button class="test-toggler" t-ref="toggler">toggle</button>`;
        static props = ["*"];
        setup() {
            useEmojiPicker(useRef("toggler"), {
                onSelect: () => {},
                onClose: () => expect.step("closed"),
            });
        }
    }
    class Parent extends Component {
        static components = { Host };
        static template = xml`<Host t-if="state.show"/>`;
        static props = ["*"];
        setup() {
            this.state = useState({ show: true });
        }
    }
    const parent = await mountWithCleanup(Parent);

    await click(".test-toggler");
    await waitFor(".o-EmojiPicker");

    parent.state.show = false;
    await animationFrame();
    expect(".o-EmojiPicker").toHaveCount(0);
    expect.verifySteps(["closed"]);
});
