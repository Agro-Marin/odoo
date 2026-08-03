// @ts-check

/**
 * @module tests/views/list/list_selection
 *
 * The long-touch selection timer armed by ``onRowTouchStart`` must not outlive
 * the component that armed it: ``t-on-touchstart`` is bound on every data row,
 * so a touch-and-hold followed by a navigation inside the threshold would
 * otherwise toggle selection on a torn-down renderer's list.
 */

import { destroy, expect, test } from "@odoo/hoot";
import { advanceTime } from "@odoo/hoot-mock";
import { Component, xml } from "@odoo/owl";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import { useListSelection } from "@web/views/list/list_selection";

const LONG_TOUCH_THRESHOLD = 400;

function mountSelectionHost(/** @type {any} */ onToggle) {
    class Host extends Component {
        static template = xml`<div/>`;
        static props = {};
        /** @type {ReturnType<typeof useListSelection>} */
        sel;

        setup() {
            this.sel = useListSelection(
                {
                    getProps: () =>
                        /** @type {any} */ ({ list: { selection: [], records: [] } }),
                    getAllowSelectors: () => true,
                    toggleRecordSelection: onToggle,
                    getEnv: () => ({ isSmall: true }),
                },
                { longTouchThreshold: LONG_TOUCH_THRESHOLD },
            );
        }
    }
    return mountWithCleanup(Host);
}

test("a pending long touch is cancelled when the component is destroyed", async () => {
    let toggled = 0;
    const host = await mountSelectionHost(() => toggled++);

    host.sel.onRowTouchStart(
        /** @type {any} */ ({ id: "rec1" }),
        /** @type {any} */ ({ stopPropagation() {} }),
    );
    destroy(host);
    await advanceTime(LONG_TOUCH_THRESHOLD * 2);

    expect(toggled).toBe(0);
});

test("a long touch that completes before destroy still toggles selection", async () => {
    let toggled = 0;
    const host = await mountSelectionHost(() => toggled++);

    host.sel.onRowTouchStart(
        /** @type {any} */ ({ id: "rec1" }),
        /** @type {any} */ ({ stopPropagation() {} }),
    );
    await advanceTime(LONG_TOUCH_THRESHOLD * 2);

    expect(toggled).toBe(1);
});
