import { registry } from "@web/core/registry";
import { contains } from "@web/../tests/utils";

const cannedResponseButtonSelector = "button[title='Insert a Canned response']";

registry.category("web_tour.tours").add("portal_composer_actions_tour_internal_user", {
    steps: () => [
        {
            trigger: `#chatterRoot:shadow .o-mail-Composer ${cannedResponseButtonSelector}`,
            run: "click",
        },
        {
            trigger: "#chatterRoot:shadow .o-mail-Composer-input",
            // `contains` polls, unlike the previous one-shot `this.anchor.value`
            // read: the click mutates `composer.composerText`, and the textarea
            // only shows it after OWL re-renders the `t-model` binding, which
            // happens after this step's trigger (an element that already
            // existed) has matched.
            async run() {
                await contains(".o-mail-Composer-input", {
                    value: "::",
                    target: document.querySelector("#chatterRoot").shadowRoot,
                });
            },
        },
        {
            trigger:
                "#chatterRoot:shadow .o-mail-Composer-suggestion:contains(Hello, how may I help you?)",
        },
    ],
});

registry.category("web_tour.tours").add("portal_composer_actions_tour_portal_user", {
    steps: () => [
        {
            trigger: `#chatterRoot:shadow .o-mail-Composer:not(:has(${cannedResponseButtonSelector}))`,
        },
    ],
});
