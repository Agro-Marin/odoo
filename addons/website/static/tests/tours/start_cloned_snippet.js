import {
    clickOnSnippet,
    insertSnippet,
    registerWebsitePreviewTour,
} from "@website/js/tours/tour_utils";

registerWebsitePreviewTour(
    "website_start_cloned_snippet",
    {
        edition: true,
        url: "/",
    },
    () => {
        const countdownSnippet = {
            name: "Countdown",
            id: "s_countdown",
        };
        return [
            ...insertSnippet(countdownSnippet),
            ...clickOnSnippet(countdownSnippet),
            {
                content: "Click on clone snippet",
                trigger: ".oe_snippet_clone",
                run: "click",
            },
            {
                content:
                    "Check that the cloned snippet has a canvas and that something has been drawn inside of it",
                trigger: ":iframe .s_countdown:eq(1) canvas",
                run: function () {
                    if (
                        !this.anchor
                            .getContext("2d")
                            .getImageData(0, 0, 1000, 1000)
                            .data.includes(1)
                    ) {
                        console.error("The cloned snippet should have been started");
                    }
                },
            },
        ];
    },
);
