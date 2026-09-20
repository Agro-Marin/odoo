import { stepUtils } from "@web_tour/tour_utils";
import {
    clickOnEditAndWaitEditMode,
    registerWebsitePreviewTour,
} from "@website/js/tours/tour_utils";

registerWebsitePreviewTour(
    "full_screen_web_editor",
    {
        url: "/slides",
    },
    () => [
        stepUtils.waitIframeIsReady(),
        {
            trigger: ':iframe a:contains("Basics of Gardening")',
            run: "click",
        },
        {
            trigger:
                ':iframe a.o_wslides_js_slides_list_slide_link:contains("Home Gardening")[href*="fullscreen=1"]',
            run: "click",
        },
        {
            trigger: ":iframe .o_wslides_fs_main",
        },
        ...clickOnEditAndWaitEditMode(),
        {
            trigger: ":iframe .o_wslides_lesson_main",
        },
    ],
);
