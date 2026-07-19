// @ts-check

/**
 * AUDIT CHALLENGE — a dropdown option may be selected against a query that no
 * longer matches the input.
 *
 * `onInput` arms the debounce but does not invalidate the currently rendered
 * options, and `selectOption` guards only `!option || option.unselectable` —
 * unlike the keydown path, which awaits `loadingPromise` before acting. So
 * while a newer search is still debounced, the options built for the PREVIOUS
 * query stay on screen and remain clickable.
 *
 * For a many2one this is how a "Create <name>" row quick-creates a record under
 * the earlier, partial text while the input already reads something else.
 *
 * The existing autocomplete tests all call `runAllTimers()` before clicking,
 * which closes exactly this window — hence no coverage.
 */

import { expect, test } from "@odoo/hoot";
import { runAllTimers } from "@odoo/hoot-dom";
import { Component, useState, xml } from "@odoo/owl";
import { contains, mountWithCleanup } from "@web/../tests/web_test_helpers";
import { AutoComplete } from "@web/components/autocomplete/autocomplete";

/** Records which query string each selected option was built from. */
const selected = [];

class Parent extends Component {
    static components = { AutoComplete };
    static template = xml`<AutoComplete value="state.value" sources="sources"/>`;
    static props = [];

    state = useState({ value: "" });
    sources = [
        {
            options: (request) => [
                {
                    label: `Create "${request}"`,
                    // Close over the request that produced this option — the
                    // real many2one quick-create does exactly this.
                    onSelect: () => selected.push(request),
                },
            ],
        },
    ];
}

test("an option is never selected against a superseded query", async () => {
    selected.length = 0;
    await mountWithCleanup(Parent);

    // First query settles and renders its option.
    await contains(".o-autocomplete input").edit("ab", { confirm: false });
    await runAllTimers();
    expect(".o-autocomplete--dropdown-item").toHaveCount(1);
    expect(queryTextOfFirstOption()).toBe(`Create "ab"`);

    // The user keeps typing. The debounce is re-armed, so the "ab" option is
    // still on screen while the input already reads "abcdefgh".
    await contains(".o-autocomplete input").edit("abcdefgh", { confirm: false });
    expect(".o-autocomplete input").toHaveValue("abcdefgh");

    // Clicking now must NOT act on the stale option. Either the selection is
    // rejected outright, or it resolves against the current query — but it must
    // never quick-create "ab" while the input says "abcdefgh".
    await contains(".o-autocomplete--dropdown-item").click();
    expect(selected).not.toInclude("ab");
});

function queryTextOfFirstOption() {
    return document.querySelector(".o-autocomplete--dropdown-item")?.textContent.trim();
}
