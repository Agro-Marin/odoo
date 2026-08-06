import { getDoublePatchedPairs } from "@mail/../tests/patch_audit";
import { describe, expect, test } from "@odoo/hoot";

describe.current.tags("headless");

/**
 * Bundle glob order is an undeclared dependency system: when two modules patch
 * the same method of the same target, which `super` runs first is decided by
 * asset-bundle file order and nothing asserts it. Every live double-patched
 * `(target, method)` pair must therefore be consciously allowlisted here.
 */

// On failure: `getDoublePatchedPairs()` in the console lists the colliding
// pairs and `patchInfo(target).extensions` names their patchers; make the patch
// `super`-transparent or explicitly ordered, then allowlist the pair. Labels
// come from `patchTargetLabel()`, so same-named classes share one
// ("Thread.prototype" covers both the model and the component). Entries whose
// second patcher is in a bundle not loaded here are harmless: the assertion is
// a subset check.
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
    // sms + snailmail each extend mail's Failure model, type-guarded on
    // notification type with a super fallback -> order-independent.
    "Failure.prototype :: body",
    "Failure.prototype :: iconSrc",
    // web FormController.setup extended by the chatter (mail) + another module;
    // super-calling setup patch, order-independent.
    "FormController.prototype :: setup",
    "MailGuest.prototype :: setup",
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
    // bus test mocks (mock_base_worker + mock_websocket) both extend start().
    "MockServer.prototype :: start",
    // sms + snailmail each extend mail's Notification model, type-guarded on
    // notification_type with a super fallback -> order-independent.
    "Notification.prototype :: failureMessage",
    "Notification.prototype :: icon",
    "OutOfFocusService.prototype :: onWindowFocus",
    // html_editor + mail each extend PropertyValue.setup; super-calling.
    "PropertyValue.prototype :: setup",
    "ResPartner.prototype :: setup",
    "ResPartner.prototype :: voipName",
    "Store.prototype :: _hasFullscreenUrlOnUpdate",
    "Store.prototype :: computeGlobalCounter",
    "Store.prototype :: getMessagePostParams",
    "Store.prototype :: onLinkFollowed",
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
    // Exhaustive gate: audit EVERY live pair, not only those on a curated set
    // of mail-surface targets — bundle order decides the `super` chain of a
    // double-patched web service or field just the same.
    const unknown = [...live].filter((pair) => !KNOWN_DOUBLE_PATCHES.has(pair));
    expect(unknown).toEqual([], {
        message:
            "new double-patched (target, method) pairs — bundle order now defines their" +
            " `super` chain; review and allowlist them in KNOWN_DOUBLE_PATCHES" +
            " (patch_order_audit.test.js)",
    });

    // Rot report: surface allowlist entries that are no longer double-patched so
    // the list can be pruned. Deliberately a warning, not a failure: an entry is
    // also dormant when its second patcher lives in a bundle this suite does not
    // load (enterprise whatsapp/voip/knowledge), so the prune/keep call is human.
    const staleCandidates = [...KNOWN_DOUBLE_PATCHES].filter((pair) => !live.has(pair));
    if (staleCandidates.length) {
        console.warn(
            `[patch-order-audit] ${staleCandidates.length} allowlist entries are not` +
                ` double-patched in this bundle. Prune the ones whose patch was removed;` +
                ` keep the ones whose second patcher is in an addon not loaded here:\n` +
                staleCandidates.join("\n"),
        );
    }
});
