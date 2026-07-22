import { dragenterFiles } from "@web/../tests/utils";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";

const MEETING_READY_STEP = "meeting-view-ready";

function getMeetingViewTourSteps({ inWelcomePage = false } = {}) {
    const steps = [
        { trigger: ".o-mail-Meeting", content: MEETING_READY_STEP },
        {
            trigger: ".o-mail-Meeting [title='Invite People']",
            run: "click",
        },
        { trigger: ".o-mail-Meeting .o-mail-ActionPanel:contains('Invite people')" },
        {
            trigger: ".o-mail-Meeting [title='Invite People']", // close it
            run: "click",
        },
        { trigger: ".o-mail-Meeting:not(:has(.o-mail-ActionPanel))" },
        {
            trigger: ".o-mail-Meeting [title='Invite People']",
            run: "click",
        },
        { trigger: ".o-mail-Meeting .o-mail-ActionPanel:contains('Invite people')" },
        {
            trigger: ".o-mail-Meeting [title='Chat']",
            run: "click",
        },
        {
            trigger:
                ".o-mail-Meeting .o-mail-ActionPanel .o-mail-Thread:contains('john (base.group_user) and bob (base.group_user)')",
        },
        {
            trigger: ".o-mail-Message[data-persistent]:contains('Hello everyone!')",
            run: "hover && click .o-mail-Message-actions button[title='Expand']",
        },
        {
            trigger: ".o-dropdown-item:contains('Mark as Unread')",
            run: "click",
        },
        { trigger: ".o-mail-Meeting [title='Chat']:has(.badge:contains(1))" },
        {
            trigger: ".o-mail-Thread-banner span:contains('Mark as Read')",
            run: "click",
        },
        {
            trigger: ".o-mail-Meeting [title='Chat']:not(:has(.badge))",
            async run({ waitFor }) {
                const files = [
                    new File(["hi there"], "file2.txt", { type: "text/plain" }),
                ];
                await dragenterFiles(".o-mail-Meeting .o-mail-ActionPanel", files);
                // Ensure other dropzones such as discuss or chat window dropzones are not active in meeting view.
                await waitFor(".o-Dropzone", { only: true });
            },
        },
        {
            trigger: ".o-mail-Meeting [title='Close panel']",
            run: "click",
        },
        { trigger: ".o-mail-Meeting:not(:has(.o-mail-ActionPanel))" },
        {
            trigger: ".o-mail-Meeting [title='Exit Fullscreen']",
            run: "click",
        },
        { trigger: "body:not(:has(.o-mail-Meeting))" },
    ];
    if (inWelcomePage) {
        steps.unshift({ trigger: "[title='Join Channel']", run: "click" });
    }
    return steps;
}

registry
    .category("web_tour.tours")
    .add("discuss.meeting_view_tour", {
        steps: () => {
            // Avoid starting with mic/camera to prevent an unhandleable browser permission popup.
            browser.localStorage.setItem("discuss_call_preview_join_mute", "true");
            browser.localStorage.setItem("discuss_call_preview_join_video", "false");
            const steps = getMeetingViewTourSteps();
            // Post the message from the meeting view's own composer, which is
            // focused as soon as the view is up -- hence right AFTER the
            // readiness step and before the invite-panel steps, which replace
            // the side panel and leave no focused composer to type into.
            // Located by marker rather than by a literal index because the
            // welcome-page variant unshifts an extra step at the front.
            //
            // This used to be `steps.find(...)`, which returns the step OBJECT;
            // `splice` coerced it to NaN -> 0, injecting these steps ahead of
            // everything -- so the tour typed into a composer before anything
            // had waited for the meeting view to exist.
            const meetingReadyIndex = steps.findIndex(
                (step) => step.content === MEETING_READY_STEP,
            );
            steps.splice(
                meetingReadyIndex + 1,
                0,
                {
                    trigger: ".o-mail-Composer.o-focused .o-mail-Composer-input",
                    run: "edit Hello everyone!",
                },
                {
                    trigger: ".o-mail-Composer button[title='Send']:enabled",
                    run: "click",
                },
            );
            return steps;
        },
    })
    .add("discuss.meeting_view_public_tour", {
        steps: () => getMeetingViewTourSteps({ inWelcomePage: true }),
    });
