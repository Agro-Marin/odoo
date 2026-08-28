// @ts-check

import { expect, test } from "@odoo/hoot";
import { animationFrame, runAllTimers } from "@odoo/hoot-mock";
import {
    getMockEnv,
    mountWithCleanup,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { PagerIndicator } from "@web/components/pager/pager_indicator";
import { PagerEvent } from "@web/core/events";
import { config as transitionConfig } from "@web/core/transition";

test("displays the pager indicator", async () => {
    patchWithCleanup(transitionConfig, { disabled: true });
    await mountWithCleanup(PagerIndicator, { noMainContainer: true });
    expect(".o_pager_indicator").toHaveCount(0, {
        message: "the pager indicator should not be displayed",
    });
    /** @type {any} */ (getMockEnv()).bus.trigger(PagerEvent.UPDATED, {
        value: "1-4",
        total: 10,
    });
    await animationFrame();
    expect(".o_pager_indicator").toHaveCount(1, {
        message: "the pager indicator should be displayed",
    });
    expect(".o_pager_indicator").toHaveText("1-4 / 10");
    await runAllTimers();
    await animationFrame();
    expect(".o_pager_indicator").toHaveCount(0, {
        message: "the pager indicator should not be displayed",
    });
});
