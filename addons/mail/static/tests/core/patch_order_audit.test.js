import { getDoublePatchedPairs } from "@mail/../tests/patch_audit";
import { describe, expect, test } from "@odoo/hoot";

describe.current.tags("headless");

/**
 * F13 — bundle glob order is an undeclared dependency system: when two
 * modules patch the same method of the same target, which `super` runs
 * first is decided by asset-bundle file order, and nothing asserts it.
 * Import-edge detection between patch modules is impractical (patches are
 * import side effects; the ESM graph does not express "must apply after"),
 * so this test enforces the simpler invariant instead: every double-patched
 * `(target, method)` pair on the mail surface must be consciously
 * allowlisted here.
 *
 * If this test fails: you (or a bundle you loaded) added a second patch to
 * a method that is already patched elsewhere. That is sometimes fine — but
 * it makes behavior depend on bundle order. Check who else patches the
 * method (`patchInfo()` / `getDoublePatchedPairs()` in the console), make
 * sure your patch is `super`-transparent or explicitly ordered, then add
 * the pair below with a normal code review.
 *
 * Labels come from `patchTargetLabel()`: same-named classes share a label
 * (e.g. the `Thread` model and `Thread` component both read
 * "Thread.prototype").
 *
 * A pair counts as double-patched only when two extensions *declared* the
 * method (see `patchDeclaredKeys()` — `patch()` mutates extension objects
 * into `super`-chain skeletons, so raw own-key inspection over-reports).
 * The allowlist is seeded from an AST scan of every `patch()` call across
 * the community *and* enterprise checkouts, since enterprise addons
 * (whatsapp, knowledge, ai, documents, voip, ...) patch these same targets
 * and may be present in the bundle; entries for patches that are not loaded
 * in the current bundle are harmless (subset assertion).
 */
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
    "OutOfFocusService.prototype :: onWindowFocus",
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
    // Exhaustive gate (t23783 defect a): audit EVERY live double-patched pair,
    // not just those on a curated target allowlist. A previous version filtered
    // `found` by a hard-coded set of mail-surface targets, so a new double-patch
    // on any unlisted target (a web service, a field, a component we had not
    // pre-listed) passed silently even though bundle order still decided its
    // `super` chain. Any pair not explicitly allowlisted below now fails.
    const unknown = [...live].filter((pair) => !KNOWN_DOUBLE_PATCHES.has(pair));
    expect(unknown).toEqual([], {
        message:
            "new double-patched (target, method) pairs — bundle order now defines their" +
            " `super` chain; review and allowlist them in KNOWN_DOUBLE_PATCHES" +
            " (patch_order_audit.test.js)",
    });

    // Rot report (t23783 defect b): surface allowlist entries that are no longer
    // double-patched so the list can be pruned. This is intentionally NOT a hard
    // failure: an entry can be dormant simply because its second patcher lives in
    // a bundle not loaded by this suite (e.g. enterprise whatsapp/voip/knowledge
    // absent from the community bundle), and asserting on those would be a false
    // positive. Definitive stale detection needs a bundle that loads every
    // patcher — runtime knowledge this headless suite does not have — so here we
    // only warn, leaving the prune/keep decision to a human review.
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
