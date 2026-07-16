import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { prettifyMessageText } from "@mail/utils/common/format";
import { expect, test } from "@odoo/hoot";
import { makeMockEnv } from "@web/../tests/web_test_helpers";

defineMailModels();

function countMatches(html, re) {
    return (html.match(re) || []).length;
}

test("every occurrence of a repeated mention is linkified (regression: bug F)", async () => {
    await makeMockEnv();
    const result = prettifyMessageText("hi @John and again @John", {
        validMentions: { partners: [{ id: 7, name: "John" }] },
    }).toString();
    // Both "@John" occurrences must become partner links, not just the first.
    expect(countMatches(result, /data-oe-id="7"/g)).toBe(2, {
        message: "both @John mentions should be linkified",
    });
});

test("prefix-colliding mentions do not corrupt each other (regression: bug F)", async () => {
    await makeMockEnv();
    // "Jo" is a prefix of "John"; "Jo" is processed first. A first-occurrence
    // string replace splices the "Jo" placeholder into "@John".
    const result = prettifyMessageText("@John and @Jo done", {
        validMentions: {
            partners: [
                { id: 8, name: "Jo" },
                { id: 7, name: "John" },
            ],
        },
    }).toString();
    expect(result).toInclude(">@John</a>", {
        message: "@John must be linkified intact",
    });
    expect(result).toInclude(">@Jo</a>", {
        message: "@Jo must be linkified intact",
    });
    // The corruption signature: "@John" mangled into "<a ...>@Jo</a>hn".
    expect(result).not.toInclude("</a>hn", {
        message: "@John must not be mangled by the @Jo replacement",
    });
});
