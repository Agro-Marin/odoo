import {
    clickOnSnippet,
    insertSnippet,
    registerWebsitePreviewTour,
} from "@website/js/tours/tour_utils";

const wallRaceConditionClass = "image_wall_race_condition";
const preventRaceConditionSteps = [
    {
        content: "Wait a few ms to avoid race condition",
        trigger: `body:not(.${wallRaceConditionClass})`,
        run() {
            setTimeout(() => {
                document.body.classList.add(wallRaceConditionClass);
            }, 500);
        },
    },
    {
        content: "Check the race condition class is added after a few ms",
        trigger: `body.${wallRaceConditionClass}`,
        run() {
            document.body.classList.remove(wallRaceConditionClass);
        },
    },
];

const selectSignImageStep = [
    {
        trigger: ".o_customize_tab:not(:has([data-label='Re-order']))",
    },
    {
        content: "Click on image 14",
        trigger: ":iframe .s_image_gallery img[src*='library_image_14']",
        run: "click",
    },
];

const reselectSignImageSteps = [
    ...preventRaceConditionSteps,
    {
        trigger:
            ":iframe .s_image_gallery .o_masonry_col:nth-child(2):has(img[data-index='1'])",
    },
    {
        content: "Select footer",
        trigger: ":iframe footer",
        run: "click",
    },
    ...selectSignImageStep,
];

registerWebsitePreviewTour(
    "snippet_images_wall",
    {
        url: "/",
        edition: true,
    },
    () => [
        ...insertSnippet({
            id: "s_images_wall",
            name: "Images Wall",
            groupName: "Images",
        }),
        ...clickOnSnippet({
            id: "s_image_gallery",
            name: "Images Wall",
        }),
        ...selectSignImageStep,
        {
            content: "Click on add a link",
            trigger: "div[data-label='Media'] button[data-action-id='setLink']",
            run: "click",
        },
        {
            content: "Change the link of the image",
            trigger: "div[data-label='Your URL'] div[data-action-id='setUrl'] input",
            run: "edit /contactus && click body",
        },
        {
            content: "Click on move to previous",
            trigger: "div[data-label='Re-order'] button[data-action-value='prev']",
            run: "click",
        },
        {
            content: "Check if sign is in second column",
            trigger:
                ":iframe .s_image_gallery .o_masonry_col:nth-child(2):has(img[data-index='1'][src*='library_image_14'])",
        },
        ...reselectSignImageSteps,
        {
            content: "Click on move to first",
            trigger: "div[data-label='Re-order'] button[data-action-value='first']",
            run: "click",
        },
        {
            content: "Check if sign is in first column",
            trigger:
                ":iframe .s_image_gallery .o_masonry_col:nth-child(1):has(img[data-index='0'][src*='library_image_14'])",
        },
        ...reselectSignImageSteps,
        {
            content: "Click on move to previous",
            trigger: "div[data-label='Re-order'] button[data-action-value='prev']",
            run: "click",
        },
        {
            content: "Check if sign is in third column",
            trigger:
                ":iframe .s_image_gallery .o_masonry_col:nth-child(3):has(img[data-index='5'][src*='library_image_14'])",
        },
        ...reselectSignImageSteps,
        {
            content: "Click on move to next",
            trigger: "div[data-label='Re-order'] button[data-action-value='next']",
            run: "click",
        },
        {
            content: "Check if sign is in first column",
            trigger:
                ":iframe .s_image_gallery .o_masonry_col:nth-child(1):has(img[data-index='0'][src*='library_image_14'])",
        },
        ...reselectSignImageSteps,
        {
            content: "Click on move to last",
            trigger: "div[data-label='Re-order'] button[data-action-value='last']",
            run: "click",
        },
        {
            content: "Check layout",
            trigger:
                ":iframe .s_image_gallery .o_masonry_col:nth-child(3):has(img[data-index='5'][src*='library_image_14'])",
        },
    ],
);
