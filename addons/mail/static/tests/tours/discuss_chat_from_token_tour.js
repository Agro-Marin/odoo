import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("discuss_chat_from_token_tour", {
    steps: () => [
        {
            content:
                "The welcome page renders: its heading is chosen by reading the thread the server injected, so it is absent when that thread has been wiped",
            trigger: ".o-mail-WelcomePage h1:contains(invited to a chat)",
        },
        {
            content: "Joining reaches the channel",
            trigger: ".o-mail-WelcomePage button[title='Join Channel']",
            run: "click",
        },
        {
            trigger: ".o-mail-Discuss",
        },
    ],
});
