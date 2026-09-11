import {
    changeOption,
    changeOptionInPopover,
    clickOnSnippet,
    insertSnippet,
    registerWebsitePreviewTour,
} from "@website/js/tours/tour_utils";

registerWebsitePreviewTour(
    "snippet_countdown",
    {
        url: "/",
        edition: true,
    },
    () => [
        ...insertSnippet({
            id: "s_countdown",
            name: "Countdown",
            groupName: "Content",
        }),
        ...clickOnSnippet({ id: "s_countdown", name: "Countdown" }),
        ...changeOptionInPopover(
            "Countdown",
            "At The End",
            "Show Message and keep countdown",
        ),
        changeOption("Countdown", "previewEndMessage"),
        {
            content: "Hover an option which has a preview",
            trigger: "[data-action-param='o_half_screen_height']",
            run: "hover",
        },
        {
            content: "Check that the countdown message is still displayed",
            trigger: ":iframe .s_countdown .s_picture",
            run() {
                const previousAnchor = document.querySelector(
                    "[data-action-param='o_half_screen_height']",
                );
                previousAnchor.dispatchEvent(new Event("mouseout"));
                previousAnchor.dispatchEvent(new Event("mouseleave"));
            },
        },
        ...changeOptionInPopover(
            "Countdown",
            "At The End",
            "Show Message and hide countdown",
        ),
        {
            content: "Check that the countdown is not displayed",
            trigger:
                ":iframe .s_countdown:has(.s_countdown_canvas_wrapper:not(:visible))",
        },
        {
            content: "Check that the message is still displayed",
            trigger: ":iframe .s_countdown .s_picture",
        },
    ],
);
