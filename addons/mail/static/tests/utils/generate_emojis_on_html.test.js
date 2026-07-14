import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { generateEmojisOnHtml } from "@mail/utils/common/format";
import { expect, test } from "@odoo/hoot";
import { markup } from "@odoo/owl";
import { makeMockEnv } from "@web/../tests/web_test_helpers";
import { loadEmoji } from "@web/components/emoji_picker/emoji_picker";

defineMailModels();

test("emoji shortcodes are replaced by emojis", async () => {
    await makeMockEnv();
    await loadEmoji();
    const result = await generateEmojisOnHtml("hello :innocent:");
    expect(result.toString()).toEqual("hello 😇");
});

test("consecutive emoji shortcodes are all replaced", async () => {
    await makeMockEnv();
    await loadEmoji();
    const result = await generateEmojisOnHtml(":innocent: :innocent:");
    expect(result.toString()).toEqual("😇 😇");
});

test("emoji sources inside words are kept as-is", async () => {
    await makeMockEnv();
    await loadEmoji();
    const result = await generateEmojisOnHtml("hello:innocent:");
    expect(result.toString()).toEqual("hello:innocent:");
});

test("unsafe content is escaped when replacing emojis", async () => {
    await makeMockEnv();
    await loadEmoji();
    const result = await generateEmojisOnHtml("<b>hi</b> :innocent:");
    expect(result.toString()).toEqual("&lt;b&gt;hi&lt;/b&gt; 😇");
});

test("markup content is preserved when replacing emojis", async () => {
    await makeMockEnv();
    await loadEmoji();
    const result = await generateEmojisOnHtml(markup`<b>hi</b> :innocent:`);
    expect(result.toString()).toEqual("<b>hi</b> 😇");
});
