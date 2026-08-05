import { patchWithCleanup } from "@web/../tests/helpers/utils";
import { registry } from "@web/core/registry";

// Resolved from the loader inside steps(): a static import would be eagerly
// resolved on every page loading web.assets_tests — killing all tours where the
// discuss bundle is absent — and would bind a second, unshared instance.
const getChannelMember = () =>
    odoo.loader.modules.get("@mail/discuss/core/common/channel_member_model")
        .ChannelMember;

registry.category("web_tour.tours").add("discuss_call_invitation.js", {
    steps: () => {
        // Call invitation is cancelled after 30s. Increase this delay for the test.
        patchWithCleanup(getChannelMember(), { CANCEL_CALL_INVITE_DELAY: 1e6 });
        return [
            { trigger: ".o-discuss-CallInvitation" },
            {
                trigger:
                    ".o-mail-CallInvitation-avatar[title='View the bob (base.group_user) and john (base.group_user) channel']",
            },
            {
                trigger:
                    ".o-discuss-CallInvitation-channelName:contains('bob (base.group_user) and john (base.group_user)')",
            },
            {
                trigger:
                    ".o-discuss-CallInvitation-description:contains('Incoming call from bob (base.group_user)')",
            },
            {
                trigger: ".o-discuss-CallInvitation-cameraPreview:not(:visible)",
            },
            {
                trigger: ".o-discuss-CallInvitation button[title='Join Call']",
            },
            {
                trigger: ".o-discuss-CallInvitation button[title='Reject']",
            },
            {
                trigger:
                    ".o-discuss-CallInvitation button[title='Show camera preview']",
                run: "click",
            },
            {
                trigger: ".o-discuss-CallInvitation-cameraPreview",
            },
            {
                trigger:
                    ".o-discuss-CallInvitation-cameraPreview button[title='Turn camera on']",
            },
            {
                trigger:
                    ".o-discuss-CallInvitation-cameraPreview button[title='Unmute']",
            },
            {
                trigger:
                    ".o-discuss-CallInvitation-cameraPreview button[title='Video Settings']",
                run: "click",
            },
            {
                trigger: "label:contains('Blur background')",
            },
            {
                trigger:
                    ".o-discuss-CallInvitation button[title='Hide camera preview']",
                run: "click",
            },
            {
                trigger: ".o-discuss-CallInvitation-cameraPreview:not(:visible)",
            },
        ];
    },
});
