import { contains, scroll } from "@web/../tests/utils";
import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("mail_message_load_order_tour", {
    steps: () => [
        {
            trigger: ".o-mail-DiscussSidebarChannel:contains(MyTestChannel)",
            run: "click",
        },
        {
            trigger: ".o-mail-Thread .o-mail-Message",
            async run() {
                await contains(".o-mail-Thread .o-mail-Message", { count: 30 });
                await contains(".o-mail-Thread", { scroll: "bottom" });
            },
        },
        {
            trigger: "*[title='Pinned Messages']",
            run: "click",
        },
        {
            content: "Click on invisible jump (should hover card to be visible)",
            trigger: ".o-mail-MessageCard-jump:not(:visible)",
            run: "click",
        },
        {
            trigger:
                ".o-mail-Thread .o-mail-Message:first .o-mail-Message-textContent:not(:contains(31))",
            async run() {
                await contains(".o-mail-Thread .o-mail-Message", { count: 31 });
                await contains(".o-mail-Thread", { scroll: 0 });
                const messages = Array.from(
                    document.querySelectorAll(".o-mail-Thread .o-mail-Message-content"),
                ).map((el) => el.innerText);
                for (let i = 0; i < 31; i++) {
                    if (messages[i] !== (i + 1).toString()) {
                        throw new Error("Wrong message order after loading around");
                    }
                }
                await scroll(".o-mail-Thread", "bottom");
            },
        },
        {
            trigger:
                ".o-mail-Thread .o-mail-Message .o-mail-Message-textContent:contains(17)",
            async run() {
                await contains(".o-mail-Thread .o-mail-Message", { count: 60 });
                const messages = Array.from(
                    document.querySelectorAll(".o-mail-Thread .o-mail-Message-content"),
                ).map((el) => el.innerText);
                for (let i = 0; i < 60; i++) {
                    if (messages[i] !== (i + 1).toString()) {
                        throw new Error("Wrong message order after loading after");
                    }
                }
            },
        },
    ],
});
