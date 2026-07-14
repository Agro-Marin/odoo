import {
    clearComposerDraft,
    restoreComposerDraft,
    saveComposerDraft,
} from "@mail/core/common/composer_draft";
import { expect, test } from "@odoo/hoot";
import { markup } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";

/** Minimal stand-in for a Composer record, as consumed by the draft module. */
function makeComposer() {
    return {
        localId: "Composer,(Thread,res.partner AND 1) OR (undefined)",
        thread: { model: "res.partner", isChannelKind: false },
        store: { "mail.message": { insert: (id) => ({ id }) } },
        composerHtml: markup`<div class='o-paragraph'><br></div>`,
        emailAddSignature: true,
        restoredFromFullComposer: false,
        replyToMessage: undefined,
    };
}

test("draft save/restore round-trip keeps content and metadata", () => {
    const composer = makeComposer();
    saveComposerDraft(composer, {
        composerHtml: markup`<p>Hello <b>world</b></p>`,
        emailAddSignature: false,
        replyToMessageId: 7,
    });
    // stored payload keeps the historical key and shape
    expect(JSON.parse(browser.localStorage.getItem(composer.localId))).toEqual({
        emailAddSignature: false,
        replyToMessageId: 7,
        composerHtml: ["markup", "<p>Hello <b>world</b></p>"],
        fromFullComposer: false,
    });
    const restored = makeComposer();
    restoreComposerDraft(restored);
    expect(restored.composerHtml).toEqual(["markup", "<p>Hello <b>world</b></p>"]);
    expect(restored.emailAddSignature).toBe(false);
    expect(restored.restoredFromFullComposer).toBe(false);
    expect(restored.replyToMessage).toEqual({ id: 7 });
});

test("draft saved from the full composer restores as recoverable", () => {
    const composer = makeComposer();
    saveComposerDraft(composer, {
        composerHtml: markup`<p>Formatted</p>`,
        emailAddSignature: true,
        replyToMessageId: undefined,
        fromFullComposer: true,
    });
    const restored = makeComposer();
    restoreComposerDraft(restored);
    expect(restored.restoredFromFullComposer).toBe(true);
    // channels have no full-composer recovery
    const channelComposer = makeComposer();
    channelComposer.thread = { model: "discuss.channel", isChannelKind: true };
    restoreComposerDraft(channelComposer);
    expect(channelComposer.restoredFromFullComposer).toBe(false);
});

test("saving an empty draft or clearing removes the stored entry", () => {
    const composer = makeComposer();
    saveComposerDraft(composer, {
        composerHtml: markup`<p>content</p>`,
        emailAddSignature: true,
    });
    expect(browser.localStorage.getItem(composer.localId)).not.toBe(null);
    saveComposerDraft(composer, {
        composerHtml: markup`<div class='o-paragraph'><br></div>`,
        emailAddSignature: true,
    });
    expect(browser.localStorage.getItem(composer.localId)).toBe(null);
    saveComposerDraft(composer, {
        composerHtml: markup`<p>content</p>`,
        emailAddSignature: true,
    });
    clearComposerDraft(composer);
    expect(browser.localStorage.getItem(composer.localId)).toBe(null);
});

test("corrupted stored draft is dropped on restore", () => {
    const composer = makeComposer();
    browser.localStorage.setItem(composer.localId, "{not json");
    restoreComposerDraft(composer);
    expect(browser.localStorage.getItem(composer.localId)).toBe(null);
    expect(composer.composerHtml.toString()).toBe(
        "<div class='o-paragraph'><br></div>",
    );
});
