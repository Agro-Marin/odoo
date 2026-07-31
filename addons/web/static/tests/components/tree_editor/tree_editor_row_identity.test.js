// @ts-check

import { beforeEach, describe, expect, test } from "@odoo/hoot";
import { click, queryAll } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { Component, useState, xml } from "@odoo/owl";
import {
    Country,
    Partner,
    Player,
    Product,
    Stage,
    Team,
} from "@web/../tests/components/tree_editor/condition_tree_editor_test_helpers";
import { defineModels, mountWithCleanup } from "@web/../tests/web_test_helpers";
import { DomainSelector } from "@web/components/domain_selector/domain_selector";

/**
 * Rows used to be keyed by `type + index`, i.e. by POSITION. Owl then reused
 * every element from a removed row onwards and re-rendered the following row's
 * data into it, so anything owl does not own — focus, caret, an open popover,
 * scroll — silently moved to a different row.
 */
describe.current.tags("desktop");

beforeEach(() => {
    defineModels([Partner, Product, Team, Player, Country, Stage]);
});

class Parent extends Component {
    static components = { DomainSelector };
    static template = xml`
        <DomainSelector resModel="'partner'" domain="state.domain"
            update="(d) => this.state.domain = d" isDebugMode="false" readonly="false"/>`;
    static props = ["*"];
    static startDomain = `["&", "&", ("foo", "=", "aaa"), ("foo", "=", "bbb"), ("foo", "=", "ccc")]`;
    setup() {
        this.state = useState({ domain: Parent.startDomain });
        Parent.last = this;
    }
}

test("deleting a row drops that row's DOM node, not the last one", async () => {
    await mountWithCleanup(Parent);
    await animationFrame();
    const rows = queryAll(".o_tree_editor_condition");
    expect(rows).toHaveLength(3);
    rows.forEach((el, i) => (el.dataset.probeStamp = String(i)));

    await click(queryAll("button[aria-label='Delete rule']")[0]);
    await animationFrame();

    const after = queryAll(".o_tree_editor_condition");
    expect(after).toHaveLength(2);
    expect(after.map((el) => el.dataset.probeStamp)).toEqual(["1", "2"]);
});

test("an externally shortened domain does not move the caret onto another row", async () => {
    await mountWithCleanup(Parent);
    await animationFrame();
    const inputs = queryAll(".o_tree_editor_condition input.o_input");
    expect(inputs.map((i) => i.value)).toEqual(["aaa", "bbb", "ccc"]);

    // The user is editing the middle row.
    const middle = /** @type {HTMLInputElement} */ (inputs[1]);
    middle.focus();
    middle.setSelectionRange(1, 1);

    // Its predecessor is removed from outside (a form onchange, the debug
    // domain input, a sibling widget).
    Parent.last.state.domain = `["&", ("foo", "=", "bbb"), ("foo", "=", "ccc")]`;
    await animationFrame();
    await animationFrame();

    // The element the caret sat in must not now be showing a different row.
    expect(middle.isConnected && middle.value !== "bbb").toBe(false, {
        message: `the focused input silently became "${middle.value}"`,
    });
    expect(
        queryAll(".o_tree_editor_condition input.o_input").map((i) => i.value),
    ).toEqual(["bbb", "ccc"]);
});
