// @ts-check

import { expect, test } from "@odoo/hoot";
import {
    defineModels,
    fields,
    models,
    mountView,
} from "@web/../tests/web_test_helpers";
import { getGoogleSlideUrl } from "@web/fields/specialized/google_slide_viewer/google_slide_viewer";

class Slide extends models.Model {
    name = fields.Char();
    presentation_url = fields.Char();
    presentation_url_page = fields.Integer();

    _records = [
        {
            id: 1,
            presentation_url:
                "https://docs.google.com/presentation/d/e/2PACX-abc123_DEF/pub",
            presentation_url_page: 0,
        },
    ];
}

defineModels([Slide]);

test("iframe src is rebuilt on the docs.google.com origin", async () => {
    await mountView({
        type: "form",
        resModel: "slide",
        resId: 1,
        arch: `<form><field name="presentation_url" widget="google_slide_viewer"/></form>`,
    });

    expect(".o_google_slide_iframe").toHaveCount(1);
    // hoot rewrites iframe src bindings to data-src to keep tests offline
    expect(".o_google_slide_iframe").toHaveAttribute(
        "data-src",
        "https://docs.google.com/presentation/d/e/2PACX-abc123_DEF/preview?slide=1",
    );
});

test("companion <name>_page field selects the previewed slide", async () => {
    Slide._records[0].presentation_url_page = 3;

    await mountView({
        type: "form",
        resModel: "slide",
        resId: 1,
        arch: `
            <form>
                <field name="presentation_url" widget="google_slide_viewer"/>
                <field name="presentation_url_page"/>
            </form>`,
    });

    // hoot rewrites iframe src bindings to data-src to keep tests offline
    expect(".o_google_slide_iframe").toHaveAttribute(
        "data-src",
        "https://docs.google.com/presentation/d/e/2PACX-abc123_DEF/preview?slide=3",
    );
});

test("non-Google URLs render no iframe", async () => {
    // "." must not act as a regex wildcard: docsXgoogle.com is not Google
    Slide._records[0].presentation_url =
        "https://docsXgoogle.com/presentation/d/e/2PACX-abc123/pub";

    await mountView({
        type: "form",
        resModel: "slide",
        resId: 1,
        arch: `<form><field name="presentation_url" widget="google_slide_viewer"/></form>`,
    });

    expect(".o_google_slide_iframe").toHaveCount(0);
});

test("getGoogleSlideUrl encodes the page and pins the origin", () => {
    expect(
        getGoogleSlideUrl("https://docs.google.com/presentation/d/abc-123/edit", 2),
    ).toBe("https://docs.google.com/presentation/d/abc-123/preview?slide=2");
    // page is URL-encoded, so it cannot smuggle extra query params
    expect(
        getGoogleSlideUrl(
            "https://docs.google.com/presentation/d/abc-123/edit",
            "1&evil=1",
        ),
    ).toBe("https://docs.google.com/presentation/d/abc-123/preview?slide=1%26evil%3D1");
    expect(getGoogleSlideUrl("https://evil.com/docs.google.com/d/abc", 1)).toBe(false);
});
