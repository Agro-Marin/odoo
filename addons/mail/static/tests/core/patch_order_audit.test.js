import { getDoublePatchedPairs } from "@mail/../tests/patch_audit";
import { describe, expect, test } from "@odoo/hoot";

describe.current.tags("headless");

const KNOWN_DOUBLE_PATCHES = new Set([
    "Activity.prototype :: markAsDone",
    "Activity.prototype :: setup",
    "ActivityMenu.prototype :: availableViews",
    "ActivityMenu.prototype :: openActivityGroup",
    "AttachmentUploadService.prototype :: _buildFormData",
    "ChatWindow.prototype :: _onClose",
    "ChatWindow.prototype :: close",
    "ChatWindow.prototype :: setup",
    "Chatter.prototype :: setup",
    "Composer :: components",
    "Composer.prototype :: allowUpload",
    "Composer.prototype :: hasGifPicker",
    "Composer.prototype :: isRevivingWhatsapp",
    "Composer.prototype :: isSendButtonDisabled",
    "Composer.prototype :: onKeydown",
    "Composer.prototype :: placeholder",
    "Composer.prototype :: setup",
    "Composer.prototype :: shouldHideFromMessageListOnDelete",
    "Discuss.prototype :: setup",
    "DiscussApp.prototype :: computeChats",
    "DiscussApp.prototype :: setup",
    "DiscussClientAction.prototype :: closeWelcomePage",
    "DiscussClientAction.prototype :: restoreDiscussThread",
    "DiscussClientAction.prototype :: setup",
    "DiscussSidebarCategory.prototype :: actions",
    "DiscussSidebarChannel.prototype :: attClassContainer",
    "Failure.prototype :: body",
    "Failure.prototype :: iconSrc",
    "FormController.prototype :: setup",
    "Message.prototype :: canForward",
    "Message.prototype :: canReplyTo",
    "Message.prototype :: edit",
    "Message.prototype :: isTranslatable",
    "Message.prototype :: onClick",
    "Message.prototype :: openRecord",
    "Message.prototype :: quickActionCount",
    "Message.prototype :: remove",
    "Message.prototype :: setup",
    "Message.prototype :: shouldHideFromMessageListOnDelete",
    "Message.prototype :: showSeenIndicator",
    "MessagingMenu.prototype :: _tabs",
    "MessagingMenu.prototype :: beforeOpen",
    "MessagingMenu.prototype :: getFailureNotificationName",
    "MessagingMenu.prototype :: openFailureView",
    "MessagingMenu.prototype :: setup",
    "MockServer.prototype :: start",
    "Notification.prototype :: failureMessage",
    "Notification.prototype :: icon",
    "OutOfFocusService.prototype :: onWindowFocus",
    "PropertyValue.prototype :: setup",
    "ResPartner.prototype :: setup",
    "ResPartner.prototype :: voipName",
    "Store.prototype :: _hasFullscreenUrlOnUpdate",
    "Store.prototype :: computeGlobalCounter",
    "Store.prototype :: getMessagePostParams",
    "Store.prototype :: onStarted",
    "Store.prototype :: onUpdateActivityGroups",
    "Store.prototype :: onlineMemberStatuses",
    "Store.prototype :: setup",
    "Store.prototype :: sortMembers",
    "SuggestionService.prototype :: getSupportedDelimiters",
    "SuggestionService.prototype :: searchSuggestions",
    "Thread :: getOrFetch",
    "Thread.prototype :: _computeDiscussAppCategory",
    "Thread.prototype :: _computeDisplayInSidebar",
    "Thread.prototype :: _computeOfflineMembers",
    "Thread.prototype :: allowCalls",
    "Thread.prototype :: allowDescription",
    "Thread.prototype :: allowedToLeaveChannelTypes",
    "Thread.prototype :: allowedToUnpinChannelTypes",
    "Thread.prototype :: autoOpenChatWindowOnNewMessage",
    "Thread.prototype :: avatarUrl",
    "Thread.prototype :: canLeave",
    "Thread.prototype :: canUnpin",
    "Thread.prototype :: composerDisabled",
    "Thread.prototype :: composerDisabledText",
    "Thread.prototype :: composerPlaceholder",
    "Thread.prototype :: computeCorrespondent",
    "Thread.prototype :: conversationStartSubtitle",
    "Thread.prototype :: conversationStartTitle",
    "Thread.prototype :: correspondents",
    "Thread.prototype :: displayName",
    "Thread.prototype :: fetchThreadData",
    "Thread.prototype :: getFetchParams",
    "Thread.prototype :: hasAttachmentPanel",
    "Thread.prototype :: hasMemberList",
    "Thread.prototype :: imStatusMember",
    "Thread.prototype :: importantCounter",
    "Thread.prototype :: inChathubOnNewMessage",
    "Thread.prototype :: isCallDisplayedInChatWindow",
    "Thread.prototype :: isChatChannel",
    "Thread.prototype :: leaveChannel",
    "Thread.prototype :: membersThatCanSeen",
    "Thread.prototype :: notifyWhenOutOfFocus",
    "Thread.prototype :: onPinStateUpdated",
    "Thread.prototype :: open",
    "Thread.prototype :: openRecordActionRequest",
    "Thread.prototype :: post",
    "Thread.prototype :: setActiveURL",
    "Thread.prototype :: setAsDiscussThread",
    "Thread.prototype :: setup",
    "Thread.prototype :: shouldSubscribeToBusChannel",
    "Thread.prototype :: transcriptUrl",
    "Thread.prototype :: typesAllowingCalls",
    "Thread.prototype :: unpin",
    "ThreadAction.prototype :: _condition",
]);

test("every live double-patch is consciously allowlisted", () => {
    const live = new Set(getDoublePatchedPairs());
    // `unknown` is empty both when every live pair is allowlisted and when the
    // registry introspection returns nothing at all -- only the second is a
    // broken audit, and the assertion below cannot tell them apart. Same guard
    // tooling/architecture/test_gate_adr_coverage.py puts on its own discovery
    // rule. Measured at 329145a4b82, this bundle carries 25 live pairs; the
    // floor sits far under that so an addon legitimately dropping a patch
    // cannot trip it, while a getPatchedTargets() that stops reporting is
    // caught immediately.
    expect(live.size).toBeGreaterThan(10);
    const unknown = [...live].filter((pair) => !KNOWN_DOUBLE_PATCHES.has(pair));
    expect(unknown).toEqual([], {
        message:
            "new double-patched (target, method) pairs — bundle order now defines their" +
            " `super` chain; review and allowlist them in KNOWN_DOUBLE_PATCHES" +
            " (patch_order_audit.test.js)",
    });

    // The mirror question -- "is any allowlist entry no longer double-patched?"
    // -- is deliberately not asked here, because a bundle cannot answer it.
    // `getDoublePatchedPairs()` reads the runtime patch registry, which sees
    // only the addons this page loaded, and CI runs this suite scoped
    // (`&module_scope=mail`); every pair whose second patcher lives in
    // im_livechat, whatsapp, voip, knowledge, sms, snailmail, ... is therefore
    // absent for that reason alone, indistinguishable from one whose patch was
    // really removed. The advisory that used to stand here listed both kinds
    // together and asked the reader to separate them by hand. Measured once on
    // the scoped run at 17179890aea, against a patch index over all four
    // addons roots: of the 82 entries it named, 81 were still double-patched
    // elsewhere in the tree and exactly one -- MailGuest.prototype :: setup,
    // pruned in the same change -- was genuinely stale. That reading is frozen:
    // it is the argument for removing the advisory, not a live figure.
    //
    // Staleness is a cross-repo *static* fact, the same shape as the one
    // js_private_access.py asks (ADR-0028): answering it needs a patch index
    // spanning odoo + enterprise + agromarin + design-themes, not a bundle.
    // `tooling/patchorder/patchorder.py` is that sweep: run it before adding
    // to or trusting this list. It reads the entries below rather than
    // restating them, and its README carries why it gates nothing and what a
    // blocking version would need. A stale entry is harmless in itself -- it
    // only widens what this test accepts without review -- which is why it is
    // swept rather than gated.
});
