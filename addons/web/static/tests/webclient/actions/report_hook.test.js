// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { Component, useRef, xml } from "@odoo/owl";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import {
    enrich,
    useEnrichWithActionLinks,
} from "@web/webclient/actions/reports/report_hook";

class EnrichHost extends Component {
    static template = xml`
        <div t-ref="root">
            <span res-id="1" res-model="partner" view-type="form" class="tgt">x</span>
            <span res-id="2" res-model="partner" view-type="form" class="tgt">y</span>
            <span class="untouched">z</span>
        </div>`;
    static props = {};
    setup() {
        this.root = useRef("root");
        useEnrichWithActionLinks(this.root);
    }
}

describe.current.tags("desktop");

test("every matching element is wrapped in exactly one action anchor", async () => {
    await mountWithCleanup(EnrichHost);
    expect(".tgt").toHaveCount(2);
    expect("a > .tgt").toHaveCount(2);
    expect("a > a").toHaveCount(0);
    expect("a > .untouched").toHaveCount(0);
});

test("a wrapped element still matches the selector it was found by", async () => {
    const comp = await mountWithCleanup(EnrichHost);
    expect(
        comp.root.el.querySelectorAll("[res-id][res-model][view-type]"),
    ).toHaveLength(2);
});

test("re-running enrich on already-enriched DOM adds nothing", async () => {
    const comp = await mountWithCleanup(EnrichHost);
    const rootEl = comp.root.el;
    const anchorsAfterMount = rootEl.querySelectorAll("a").length;
    expect(anchorsAfterMount).toBe(2);

    enrich(comp, rootEl);
    enrich(comp, rootEl);

    expect(rootEl.querySelectorAll("a")).toHaveLength(anchorsAfterMount);
    expect("a > a").toHaveCount(0);
    expect("a > .tgt").toHaveCount(2);
});

test("enrich still wraps elements added after the first pass", async () => {
    const comp = await mountWithCleanup(EnrichHost);
    const rootEl = comp.root.el;
    const fresh = document.createElement("span");
    fresh.setAttribute("res-id", "3");
    fresh.setAttribute("res-model", "partner");
    fresh.setAttribute("view-type", "form");
    fresh.classList.add("tgt");
    rootEl.appendChild(fresh);

    enrich(comp, rootEl);

    expect("a > .tgt").toHaveCount(3);
    expect("a > a").toHaveCount(0);
});
