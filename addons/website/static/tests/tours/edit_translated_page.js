import { registry } from "@web/core/registry";
import { clickOnEditAndWaitEditModeInTranslatedPage } from "@website/js/tours/tour_utils";

registry.category("web_tour.tours").add("edit_translated_page_redirect", {
    url: "/nl/contactus",
    steps: () => [
        {
            content: "Enter backend",
            trigger: "a.o_frontend_to_backend_edit_btn",
            run: "click",
            expectUnloadPage: true,
        },
        {
            content: "Check the data-for attribute",
            trigger: ':iframe main span[data-for="contactus_form"]:not(:visible)',
        },
        ...clickOnEditAndWaitEditModeInTranslatedPage(),
        {
            content: "Go to /nl",
            trigger: "body",
            run: () => {
                location.href = "/nl";
            },
            expectUnloadPage: true,
        },
        {
            content: "Enter backend",
            trigger: "a.o_frontend_to_backend_edit_btn",
            run: "click",
            expectUnloadPage: true,
        },
        ...clickOnEditAndWaitEditModeInTranslatedPage(),
    ],
});
