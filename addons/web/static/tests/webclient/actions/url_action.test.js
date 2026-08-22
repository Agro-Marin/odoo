// @ts-check

import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import {
    getService,
    makeMockEnv,
    mountWithCleanup,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { MainComponentsContainer } from "@web/ui/main_components_container";

test("execute an 'ir.actions.act_url' action with target 'self'", async () => {
    patchWithCleanup(browser.location, {
        assign: (url) => {
            expect.step(url);
        },
    });
    await makeMockEnv();
    await getService("action").doAction({
        type: "ir.actions.act_url",
        target: "self",
        url: "/my/test/url",
    });
    expect.verifySteps(["/my/test/url"]);
});

test("execute an 'ir.actions.act_url' action with onClose option", async () => {
    patchWithCleanup(browser, {
        open: () => expect.step("browser open"),
    });
    await makeMockEnv();
    const options = {
        onClose: () => expect.step("onClose"),
    };
    await getService("action").doAction(
        { type: "ir.actions.act_url", url: "/my/test/url" },
        options,
    );
    expect.verifySteps(["browser open", "onClose"]);
});

test("an 'ir.actions.act_url' action without url does nothing", async () => {
    patchWithCleanup(browser, {
        open: (url) => expect.step(`open ${url}`),
    });
    patchWithCleanup(browser.location, {
        assign: (url) => expect.step(`assign ${url}`),
    });
    await makeMockEnv();
    await getService("action").doAction({ type: "ir.actions.act_url" });
    await getService("action").doAction({ type: "ir.actions.act_url", target: "self" });
    await getService("action").doAction({
        type: "ir.actions.act_url",
        target: "download",
        url: "",
    });
    expect.verifySteps([]);
});

const UNSAFE_URLS = [
    "javascript:alert()",
    "JavaScript:alert()",
    "  javascript:alert()",
    "data:text/html,<script></script>",
    "vbscript:msgbox(1)",
    "//evil.example",
    "httpx://evil.example",
];

for (const url of UNSAFE_URLS) {
    test(`an 'ir.actions.act_url' action is blocked for ${JSON.stringify(url)}`, async () => {
        patchWithCleanup(browser.location, {
            assign: (assigned) => expect.step(`assign ${assigned}`),
        });
        patchWithCleanup(browser, {
            open: (opened) => expect.step(`open ${opened}`),
        });
        await makeMockEnv();
        await mountWithCleanup(MainComponentsContainer);
        await getService("action").doAction({
            type: "ir.actions.act_url",
            target: "self",
            url,
        });
        await animationFrame();
        expect.verifySteps([]);
        expect(".o_notification").toHaveCount(1);
        expect(".o_notification").toHaveText(/unsafe URL/);
    });
}

test("a blob url is opened as-is, not turned into a relative path", async () => {
    patchWithCleanup(browser, {
        open: (url) => {
            expect.step(url);
            return { closed: false };
        },
    });
    await makeMockEnv();
    await mountWithCleanup(MainComponentsContainer);
    await getService("action").doAction({
        type: "ir.actions.act_url",
        url: "blob:http://localhost:8069/2f1c-4a6b",
    });
    await animationFrame();
    expect(".o_notification").toHaveCount(0);
    expect.verifySteps(["blob:http://localhost:8069/2f1c-4a6b"]);
});

test("an absolute url keeps its scheme untouched", async () => {
    patchWithCleanup(browser, {
        open: (url) => {
            expect.step(url);
            return { closed: false };
        },
    });
    await makeMockEnv();
    for (const url of [
        "https://example.com/x",
        "http://example.com/x",
        "mailto:a@b.c",
        "ftp://example.com/x",
    ]) {
        await getService("action").doAction({ type: "ir.actions.act_url", url });
    }
    expect.verifySteps([
        "https://example.com/x",
        "http://example.com/x",
        "mailto:a@b.c",
        "ftp://example.com/x",
    ]);
});

test("a safe relative url is still normalized and opened", async () => {
    patchWithCleanup(browser.location, {
        assign: (url) => expect.step(url),
    });
    await makeMockEnv();
    await getService("action").doAction({
        type: "ir.actions.act_url",
        target: "self",
        url: "my/test/url",
    });
    expect.verifySteps(["/my/test/url"]);
});

test("a blocked url still settles the action's onClose", async () => {
    await makeMockEnv();
    await mountWithCleanup(MainComponentsContainer);
    await getService("action").doAction(
        { type: "ir.actions.act_url", url: "javascript:alert()" },
        { onClose: () => expect.step("onClose") },
    );
    expect.verifySteps(["onClose"]);
});

test("execute an 'ir.actions.act_url' action with target 'download'", async () => {
    patchWithCleanup(browser, {
        open: (url) => {
            expect.step(url);
        },
    });
    await makeMockEnv();
    await getService("action").doAction({
        type: "ir.actions.act_url",
        target: "download",
        url: "/my/test/url",
    });
    expect(".o_blockUI").toHaveCount(0);
    expect.verifySteps(["/my/test/url"]);
});
