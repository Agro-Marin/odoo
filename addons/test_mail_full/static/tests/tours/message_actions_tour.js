import { registry } from "@web/core/registry";
import { contains } from "@web/../tests/utils";

registry.category("web_tour.tours").add("star_message_tour", {
    steps: () => [
        {
            trigger:
                "#chatterRoot:shadow .o-mail-Message:not([data-starred]):contains(Test Message)",
            run: "hover && click #chatterRoot:shadow [title='Add Star']",
        },
        {
            trigger:
                "#chatterRoot:shadow .o-mail-Message[data-starred]:contains(Test Message)",
        },
    ],
});

registry.category("web_tour.tours").add("message_actions_tour", {
    steps: () => [
        {
            trigger: "#chatterRoot:shadow .o-mail-Thread .o-mail-Message",
            run: async function () {
                await contains(".o-mail-Thread .o-mail-Message", {
                    count: 1,
                    target: document.querySelector("#chatterRoot").shadowRoot,
                });
            },
        },
        {
            trigger: "#chatterRoot:shadow .o-mail-Composer-input",
            run: "edit New message",
        },
        {
            trigger:
                "#chatterRoot:shadow .o-mail-Composer button:contains(Send):enabled",
            run: "click",
        },
        {
            trigger: "#chatterRoot:shadow .o-mail-Thread .o-mail-Message",
            run: async function () {
                await contains(".o-mail-Thread .o-mail-Message", {
                    count: 2,
                    target: document.querySelector("#chatterRoot").shadowRoot,
                });
            },
        },
        {
            trigger:
                "#chatterRoot:shadow .o-mail-Message[data-persistent]:contains(New message)",
            // The toolbar is rendered as a *result* of the hover and only
            // survives while the pointer stays on the message, so this cannot
            // be split into a separate "click" step (the hover is lost between
            // steps and the button never appears). It also cannot be a plain
            // "hover && click <button>": that queries the button in the same
            // tick as the hover and intermittently finds 0 elements. Hover,
            // wait for the button to render, then click -- all within the one
            // step that owns the hover.
            async run(helpers) {
                await helpers.hover();
                // Scoped to THIS message via the step's anchor: both messages
                // carry a toolbar, so an unscoped wait matches 2 elements.
                // `contains` resolves selectors with plain querySelectorAll,
                // which has no `:contains()` pseudo -- that is a tour-engine
                // extension, usable in the click selector below but not here.
                await contains("button[title='Add a Reaction']", {
                    target: this.anchor,
                });
                await helpers.click(
                    "#chatterRoot:shadow .o-mail-Message:contains(New message) button[title='Add a Reaction']",
                );
            },
        },
        {
            trigger:
                "#chatterRoot:shadow .o-mail-QuickReactionMenu-emoji span:contains(❤️)",
            run: "click",
        },
        {
            trigger:
                "#chatterRoot:shadow .o-mail-Message:contains(New message) .o-mail-MessageReaction:contains(❤️)",
        },
        {
            // Wait for the quick-reaction menu to be gone before hovering: while
            // it is still open/closing it owns the pointer, so the message's own
            // hover toolbar (and its Edit button) is not rendered.
            trigger:
                "#chatterRoot:shadow .o-mail-Thread:not(:has(.o-mail-QuickReactionMenu))",
        },
        {
            // `[data-persistent]` as on the reaction step: without it this can
            // anchor on the optimistic (not yet persisted) copy of the message,
            // which carries no Edit action -- so the wait below times out
            // finding 0 buttons. Only visible under load, which is why it
            // reproduced in the full suite but not when run alone.
            trigger:
                "#chatterRoot:shadow .o-mail-Message[data-persistent]:contains(New message)",
            // same hover-then-render race as the reaction button above
            async run(helpers) {
                // Move the pointer OFF the message first. Clicking the emoji
                // left it over this very message, and hovering an element the
                // pointer already sits on fires no new mouseenter -- so the
                // toolbar would never (re)appear and the wait below would find
                // 0 Edit buttons. The reaction step above needs no such reset:
                // the preceding click landed on the Send button, away from it.
                await helpers.hover("#chatterRoot:shadow .o-mail-Composer-input");
                await helpers.hover();
                await contains("button[title='Edit']", { target: this.anchor });
                await helpers.click(
                    "#chatterRoot:shadow .o-mail-Message[data-persistent]:contains(New message) button[title='Edit']",
                );
            },
        },
        {
            trigger: "#chatterRoot:shadow .o-mail-Message .o-mail-Composer-input",
            run: "edit Message content changed",
        },
        {
            trigger: "#chatterRoot:shadow .o-mail-Message button:contains(save)",
            run: "click",
        },
        {
            trigger:
                "#chatterRoot:shadow .o-mail-Message:contains(Message content changed)",
            run: "hover && click #chatterRoot:shadow button[title='Delete']",
        },
        {
            trigger: "#chatterRoot:shadow button:contains(Delete)",
            run: "click",
        },
        {
            trigger: "#chatterRoot:shadow .o-mail-Thread .o-mail-Message",
            run: async function () {
                await contains(".o-mail-Thread .o-mail-Message", {
                    count: 1,
                    target: document.querySelector("#chatterRoot").shadowRoot,
                });
            },
        },
    ],
});
