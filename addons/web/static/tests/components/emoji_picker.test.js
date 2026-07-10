// @ts-check

import { expect, test } from "@odoo/hoot";
import {
    mountWithCleanup,
    patchWithCleanup,
    preloadBundle,
} from "@web/../tests/web_test_helpers";
import { EmojiPicker, loader } from "@web/components/emoji_picker/emoji_picker";
import { browser } from "@web/core/browser/browser";

preloadBundle("web.assets_emoji");

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
