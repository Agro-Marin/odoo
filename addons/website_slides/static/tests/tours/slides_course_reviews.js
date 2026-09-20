import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("course_reviews", {
    url: "/slides",
    steps: () => [
        {
            trigger: "a:contains(Basics of Gardening - Test)",
            run: "click",
            expectUnloadPage: true,
        },
        {
            trigger: "a[id=review-tab]",
            run: "click",
        },
        {
            trigger:
                "#chatterRoot:shadow .o-mail-Chatter-content:not(:has(.o-mail-Message-content))",
        },
        {
            trigger: "span:contains(Add Review)",
            run: "click",
        },
        {
            trigger:
                ".modal.modal_shown.show div.o_portal_chatter_composer_body textarea",
            run: "edit Great course!",
        },
        {
            trigger: ".modal.modal_shown.show button.o_portal_chatter_composer_btn",
            run: "click",
        },
        {
            trigger: "body:not(:has(.modal.show))",
        },
        {
            trigger: ".o_wslides_course_header_nav_review",
        },
        {
            trigger: "a[id=review-tab]:contains('Reviews (1)')",
            run: "click",
        },
        {
            trigger:
                "#chatterRoot:shadow .o-mail-Message-textContent:contains(Great course!)",
        },
        {
            trigger: "span:contains(Edit Review)",
            run: "click",
        },
        {
            trigger: "div.o_portal_chatter_composer_body textarea:value(Great course!)",
            run: "edit Mid course!",
        },
        {
            trigger:
                ".modal.modal_shown.show button.o_portal_chatter_composer_btn:contains(update review)",
            run: "click",
        },
        {
            trigger: "a[id=review-tab]",
            run: "click",
        },
        {
            trigger:
                "#chatterRoot:shadow .o-mail-Message-textContent:contains(Mid course!)",
            run: "hover && click",
        },
        {
            trigger: "#chatterRoot:shadow .o-mail-Message [title='Add a Reaction']",
            run: "click",
        },
        {
            trigger:
                "#chatterRoot:shadow .o-mail-QuickReactionMenu-emoji span:contains('👍'):not(:visible)",
            run: "click",
        },
        {
            trigger:
                "#chatterRoot:shadow .o-mail-Message .o-mail-MessageReactions:not([title='Add a Reaction'])",
        },
        {
            trigger: "#chatterRoot:shadow .o-mail-Message .o-mail-MessageReaction",
            run: "click",
        },
        {
            trigger: '#chatterRoot:shadow .o-mail-Message button:contains("Comment")',
            run: "click",
        },
        {
            trigger: "#chatterRoot:shadow .o-mail-Message .o-mail-Composer textarea",
            run: "edit Thanks for enjoying my 'mid' course, you mid student",
        },
        {
            trigger: "#chatterRoot:shadow .o-mail-Message .o-mail-Composer textarea",
            run: "press ctrl+Enter",
        },
        {
            trigger: `#chatterRoot:shadow .o_wrating_publisher_comment:contains("Thanks for enjoying my 'mid' course, you mid student")`,
        },
    ],
});
