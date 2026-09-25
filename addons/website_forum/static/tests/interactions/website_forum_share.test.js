import { beforeEach, describe, expect, test } from "@odoo/hoot";
import { freezeTime } from "@odoo/hoot-dom";
import { runAllTimers } from "@odoo/hoot-mock";
import {
    startInteractions,
    setupInteractionWhiteList,
} from "@web/../tests/public/helpers";
import { defineStyle } from "@web/../tests/web_test_helpers";

setupInteractionWhiteList(["website_forum.website_forum_share", "website.share"]);
describe.current.tags("interaction_dev");

beforeEach(() =>
    defineStyle(`* { transition: none !important; animation: none !important; }`),
);

function startForumShare({ targetType = "answer", state = "active" } = {}) {
    sessionStorage.setItem("social_share", JSON.stringify({ targetType }));
    return startInteractions(`
         <div id="wrapwrap" class="website_forum">
            <div class="o_wforum_question" data-state="${state}"></div>
         </div>
    `);
}

async function startForumShareShown(options) {
    const shown = new Promise((resolve) =>
        document.body.addEventListener("shown.bs.modal", (ev) => resolve(ev.target), {
            once: true,
        }),
    );
    const { core } = await startForumShare(options);
    return { core, modalEl: await shown };
}

function expectPageUnlocked() {
    expect(document.querySelectorAll("#oe_social_share_modal")).toHaveLength(0);
    expect(document.querySelectorAll(".modal-backdrop")).toHaveLength(0);
    expect(document.body).not.toHaveClass("modal-open");
    expect(document.body.style.overflow).toBe("");
}

test("sessionStorage social_share is cleared after start", async () => {
    sessionStorage.setItem("social_share", JSON.stringify({ targetType: "answer" }));
    expect(sessionStorage.getItem("social_share")).toEqual('{"targetType":"answer"}');
    await startInteractions(`
         <div id="wrapwrap" class="website_forum">
            <div class="o_wforum_question" data-state="active"></div>
         </div>
    `);
    expect(sessionStorage.getItem("social_share")).toBe(null);
});

describe("target types", () => {
    for (const [targetType, text] of [
        ["answer", /^By sharing you answer, you will get additional/],
        ["question", /^On average,/],
        ["default", /^Share this content to increase your chances/],
    ]) {
        test(`target type ${targetType} shows modal with website_forum.social_message_${targetType}`, async () => {
            const { core, modalEl } = await startForumShareShown({ targetType });
            expect(core.interactions).toHaveLength(2);
            expect(modalEl).toBeVisible();
            expect(modalEl.querySelector("p")).toHaveText(text);
        });
    }
});

describe("forum share state", () => {
    test("pending state doesn't show .s_share", async () => {
        const { core, modalEl } = await startForumShareShown({ state: "pending" });
        expect(core.interactions).toHaveLength(1);
        expect(modalEl).toBeVisible();
        expect(modalEl.querySelector(".s_share")).toBe(null);
    });

    test("active state shows .s_share", async () => {
        const { core, modalEl } = await startForumShareShown();
        expect(core.interactions).toHaveLength(2);
        expect(modalEl).toBeVisible();
        expect(modalEl.querySelector(".s_share")).toBeVisible();
    });
});

describe("teardown", () => {
    test("stopping while the modal is still showing leaves nothing behind", async () => {
        freezeTime();
        const { core } = await startForumShare();
        expect(document.querySelectorAll("#oe_social_share_modal")).toHaveLength(1);
        core.stopInteractions();
        await runAllTimers();
        expectPageUnlocked();
    });

    test("stopping once the modal is shown closes it and unlocks the page", async () => {
        const { core, modalEl } = await startForumShareShown();
        expect(modalEl).toBeVisible();
        expect(document.body).toHaveClass("modal-open");
        core.stopInteractions();
        expectPageUnlocked();
    });
});
