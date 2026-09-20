import { Chatbot } from "@im_livechat/core/common/chatbot_model";
import { patchWithCleanup } from "@web/../tests/helpers/utils";
import { contains } from "@web/../tests/utils";
import { registry } from "@web/core/registry";
import { Deferred } from "@web/core/utils/concurrency";

const messagesContain = (text) =>
    `.o-livechat-root:shadow .o-mail-Message:contains("${text}")`;
let chatbotDelayProcessingDef;

registry.category("web_tour.tours").add("website_livechat_chatbot_flow_tour", {
    steps: () => {
        patchWithCleanup(Chatbot.prototype, {
            async _delayThenProcessAnswerAgain(message) {
                chatbotDelayProcessingDef?.resolve();
                return await super._delayThenProcessAnswerAgain(message);
            },
        });
        patchWithCleanup(Chatbot, {
            MESSAGE_DELAY: 0,
            MULTILINE_STEP_DEBOUNCE_DELAY: 2000,
            TYPING_DELAY: 0,
        });
        return [
            {
                trigger: messagesContain("I help lost visitors find their way."),
            },
            {
                trigger: messagesContain("How can I help you?"),
                run() {
                    if (
                        this.anchor.querySelector(
                            ".o-mail-Message-actions [title='Add a Reaction']",
                        )
                    ) {
                        console.error(
                            "Reactions should not be available before thread is persisted.",
                        );
                    }
                },
            },
            {
                trigger:
                    '.o-livechat-root:shadow button:contains("I\'d like to buy the software")',
                run: "click",
            },
            {
                trigger: ".o-livechat-root:shadow .o-mail-ChatWindow",
                async run() {
                    await contains(".o-mail-Message-actions [title='Add a Reaction']", {
                        target: this.anchor.getRootNode(),
                        parent: [
                            ".o-mail-Message",
                            { text: "I'd like to buy the software" },
                        ],
                    });
                },
            },
            {
                trigger: messagesContain("Can you give us your email please?"),
            },
            {
                trigger: ".o-livechat-root:shadow .o-mail-Composer-input ",
                run: "edit No, you won't get my email!",
            },
            {
                trigger: ".o-livechat-root:shadow .o-mail-Composer-input",
                run: "press Enter",
            },
            {
                trigger: messagesContain(
                    "'No, you won't get my email!' does not look like a valid email. Can you please try again?",
                ),
            },
            {
                trigger: ".o-livechat-root:shadow .o-mail-Composer-input",
                run: "edit okfine@fakeemail.com",
            },
            {
                trigger: ".o-livechat-root:shadow .o-mail-Composer-input",
                run: "press Enter",
            },
            {
                trigger: messagesContain("Your email is validated, thank you!"),
            },
            {
                trigger: messagesContain(
                    "Would you mind providing your website address?",
                ),
            },
            {
                trigger: ".o-livechat-root:shadow .o-mail-Composer-input",
                run: "edit https://www.fakeaddress.com",
            },
            {
                trigger: ".o-livechat-root:shadow .o-mail-Composer-input",
                run: "press Enter",
            },
            {
                trigger: messagesContain(
                    "Great, do you want to leave any feedback for us to improve?",
                ),
            },
            {
                trigger: ".o-livechat-root:shadow .o-mail-Composer-input",
                run: "edit Yes, actually, I'm glad you asked!",
            },
            {
                trigger: ".o-livechat-root:shadow .o-mail-Composer-input",
                run: "press Enter",
            },
            {
                trigger: ".o-livechat-root:shadow .o-mail-Composer-input",
                run: "edit I think it's outrageous that you ask for all my personal information!",
            },
            {
                trigger: ".o-livechat-root:shadow .o-mail-Composer-input",
                run: "press Enter",
            },
            {
                trigger: ".o-livechat-root:shadow .o-mail-Composer-input",
                run: "edit I will be sure to take this to your manager!",
            },
            {
                trigger: ".o-livechat-root:shadow .o-mail-Composer-input",
                run: "press Enter",
            },
            {
                trigger: ".o-livechat-root:shadow .o-mail-Composer-input",
                run: "edit I want to say...",
            },
            {
                trigger: ".o-livechat-root:shadow .o-mail-Composer-input",
                async run(helpers) {
                    chatbotDelayProcessingDef = new Deferred();
                    let failTimeout = setTimeout(() => {
                        chatbotDelayProcessingDef.reject(
                            "Chatbot should stay in multi line step when user is typing.",
                        );
                    }, 5000);
                    chatbotDelayProcessingDef.then(() => clearTimeout(failTimeout));
                    helpers.edit("Never mind!");
                    await chatbotDelayProcessingDef;
                    chatbotDelayProcessingDef = new Deferred();
                    failTimeout = setTimeout(() => {
                        chatbotDelayProcessingDef.reject(
                            "Chatbot should stay in multi line step if user isn't done typing.",
                        );
                    }, 5000);
                    chatbotDelayProcessingDef.then(() => clearTimeout(failTimeout));
                    helpers.edit("Never mind!!!");
                    await chatbotDelayProcessingDef;
                },
            },
            {
                trigger: messagesContain("Ok bye!"),
            },
            {
                trigger:
                    ".o-livechat-root:shadow .o-mail-ChatWindow-header [title='Restart Conversation']",
                run: "click",
            },
            {
                trigger: messagesContain("Restarting conversation..."),
            },
            {
                trigger: messagesContain("Hello! I'm a bot!"),
            },
            {
                trigger: messagesContain("I help lost visitors find their way."),
            },
            {
                trigger: messagesContain("How can I help you?"),
            },
            {
                trigger: '.o-livechat-root:shadow button:contains("Pricing Question")',
                run: "click",
            },
            {
                trigger: messagesContain(
                    "For any pricing question, feel free ton contact us at pricing@mycompany.com",
                ),
            },
            {
                trigger: messagesContain(
                    "We will reach back to you as soon as we can!",
                ),
            },
            {
                trigger: messagesContain(
                    "Would you mind providing your website address?",
                ),
            },
            {
                trigger: ".o-livechat-root:shadow .o-mail-Composer-input",
                run: "edit no",
            },
            {
                trigger: ".o-livechat-root:shadow .o-mail-Composer-input",
                run: "press Enter",
            },
            {
                trigger: messagesContain(
                    "Great, do you want to leave any feedback for us to improve?",
                ),
            },
            {
                trigger: ".o-livechat-root:shadow .o-mail-Composer-input",
                run: "edit no, nothing so say",
            },
            {
                trigger: ".o-livechat-root:shadow .o-mail-Composer-input",
                run: "press Enter",
            },
            {
                trigger: messagesContain("Ok bye!"),
                run: "click",
            },
            {
                trigger:
                    ".o-livechat-root:shadow .o-mail-ChatWindow-header [title='Restart Conversation']",
                run: "click",
            },
            {
                trigger:
                    ".o-livechat-root:shadow button:contains(I want to speak with an operator)",
                run: "click",
            },
            {
                trigger: messagesContain("I will transfer you to a human."),
            },
            {
                trigger: ".o-livechat-root:shadow .o-mail-Composer-input:enabled",
            },
        ];
    },
});
