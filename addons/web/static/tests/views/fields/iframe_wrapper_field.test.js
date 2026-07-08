// @ts-check

import { expect, test } from "@odoo/hoot";
import { click, edit, queryFirst } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import {
    defineModels,
    fields,
    models,
    mountView,
} from "@web/../tests/web_test_helpers";

class Report extends models.Model {
    int_field = fields.Integer();
    html_field = fields.Html();

    _records = [
        {
            id: 1,
            html_field: /* html */ `
                <html>
                    <head>
                        <style>
                            body { color : rgb(255, 0, 0); }
                        </style>
                    </head>
                    <body>
                        <div class="nice_div"><p>Some content</p></div>
                    </body>
                </html>
            `,
        },
    ];
}

defineModels([Report]);

test("IframeWrapperField in form view with onchange", async () => {
    Report._onChanges.int_field = (record) => {
        record.html_field = record.html_field.replace("Some content", "New content");
    };
    await mountView({
        type: "form",
        resModel: "report",
        resId: 1,
        arch: /* xml */ `
            <form>
                <field name="int_field"/>
                <field name="html_field" widget="iframe_wrapper"/>
            </form>
        `,
    });

    expect("iframe:iframe .nice_div:first").toHaveInnerHTML("<p>Some content</p>");
    expect("iframe:iframe .nice_div p:first").toHaveStyle({
        color: "rgb(255, 0, 0)",
    });
    await click(".o_field_widget[name=int_field] input");
    await edit(264, { confirm: "enter" });
    await animationFrame();
    expect(queryFirst("iframe:iframe .nice_div")).toHaveInnerHTML("<p>New content</p>");
});

test("IframeWrapperField does not execute injected scripts", async () => {
    Report._records[0].html_field = /* html */ `
        <html>
            <head></head>
            <body>
                <div class="safe_content"><p>Server rendered</p></div>
                <script>
                    const el = document.createElement("div");
                    el.className = "xss_executed";
                    document.body.appendChild(el);
                </script>
            </body>
        </html>
    `;
    await mountView({
        type: "form",
        resModel: "report",
        resId: 1,
        arch: /* xml */ `
            <form>
                <field name="html_field" widget="iframe_wrapper"/>
            </form>
        `,
    });
    await animationFrame();

    // The legitimate (server-rendered) content still renders...
    expect("iframe:iframe .safe_content").toHaveCount(1);
    // ...but the injected <script> must NOT run inside the sandboxed iframe.
    expect("iframe:iframe .xss_executed").toHaveCount(0);
    // The iframe keeps same-origin (so the parent can write into it) but has no
    // allow-scripts, which is what blocks script execution.
    expect("iframe.o_preview_iframe").toHaveAttribute("sandbox", "allow-same-origin");
});
