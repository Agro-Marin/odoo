// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { queryAll } from "@odoo/hoot-dom";
import { makeMockEnv, mountWithCleanup } from "@web/../tests/web_test_helpers";
import { SkeletonView } from "@web/webclient/actions/skeleton_view";

describe.current.tags("desktop");

/** @param {Object} [props] */
async function mountSkeleton(props = {}) {
    await makeMockEnv();
    return mountWithCleanup(SkeletonView, {
        props: { onMounted: () => {}, ...props },
        noMainContainer: true,
    });
}

test("the decorative shimmer is hidden from assistive technology", async () => {
    await mountSkeleton({ viewType: "list", withControlPanel: true });

    expect(".o_skeleton_view").toHaveAttribute("aria-hidden", "true");
    expect(queryAll(".o_skeleton_view [aria-hidden='false']")).toHaveLength(0);
});

test("the shimmer contributes no text of its own", async () => {
    const skeleton = await mountSkeleton({ viewType: "list", withControlPanel: true });
    expect(skeleton.el?.textContent?.trim() ?? "").toBe("");
});

test("onMounted fires exactly once, which is what releases the dispatch", async () => {
    let mounted = 0;
    await mountSkeleton({ onMounted: () => mounted++ });
    expect(mounted).toBe(1);
});

test("an unknown view type falls back to the generic shimmer", async () => {
    const skeleton = await mountSkeleton();
    expect(skeleton.viewType).toBe("generic");

    const listSkeleton = await mountSkeleton({ viewType: "list" });
    expect(listSkeleton.viewType).toBe("list");
});

test("the control panel placeholder is opt-in", async () => {
    await mountSkeleton({ withControlPanel: false });
    expect(".o_skeleton_cp").toHaveCount(0);

    await mountSkeleton({ withControlPanel: true });
    expect(".o_skeleton_cp").toHaveCount(1);
});

test("cell widths stay inside the band the layout assumes", async () => {
    const skeleton = await mountSkeleton();
    const widths = [];
    for (let row = 0; row < 8; row++) {
        for (let col = 0; col < 5; col++) {
            widths.push(skeleton.cellWidth(row, col));
        }
    }
    expect(Math.min(...widths)).toBeGreaterThan(34);
    expect(Math.max(...widths)).toBeLessThan(80);
    expect(new Set(widths).size).toBeGreaterThan(1);
});
