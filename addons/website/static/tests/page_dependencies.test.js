import { expect, test } from "@odoo/hoot";
import { click } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup, onRpc } from "@web/../tests/web_test_helpers";
import { PageDependencies } from "@website/components/dialog/page_properties";

import { defineWebsiteModels } from "./builder/website_helpers.js";

defineWebsiteModels();

const DEPENDENCIES = {
    Page: [{ text: "Page", link: "/page-1", record_name: "Home", field_name: "url" }],
};

function mockDependencies() {
    onRpc("/web/dataset/call_kw/website/search_url_dependencies", () => DEPENDENCIES);
}

test("popover mode: dependencies are rendered by the popover service on demand", async () => {
    mockDependencies();
    await mountWithCleanup(PageDependencies, {
        props: { resIds: [1], resModel: "website.page", mode: "popover" },
    });
    await animationFrame();

    // Nothing is shown until the trigger is used: the popover service mounts
    // the content, where Bootstrap kept it in the DOM behind a `data-bs-*` shell.
    expect(".o_page_dependencies").toHaveCount(0);

    await click("a");
    await animationFrame();

    expect(".o_popover").toHaveCount(1);
    expect(".o_popover").toHaveText(/Dependencies/);
    expect(".o_popover").toHaveText(/Home/);
});

test("collapse mode: each dependency group is a native details block", async () => {
    mockDependencies();
    await mountWithCleanup(PageDependencies, {
        props: { resIds: [1], resModel: "website.page", mode: "collapse" },
    });
    await animationFrame();

    // `<details>` replaced `data-bs-toggle="collapse"`: no JS, and the summary
    // is the disclosure control.
    expect("details").toHaveCount(1);
    expect("details > summary").toHaveCount(1);
    expect("details").not.toHaveAttribute("open");
});
