// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    getAnimationOptions,
    getElementOptions,
    getMaxWidth,
} from "@web/views/graph/graph_chart_config";

describe("getMaxWidth — tooltip width from the chart area", () => {
    test("divides the area width by the golden ratio", () => {
        expect(getMaxWidth({ left: 0, right: 1000 })).toBe("618px");
    });

    test("uses the width, not the right edge", () => {
        expect(getMaxWidth({ left: 200, right: 1200 })).toBe("618px");
    });

    test("floors rather than rounds", () => {
        expect(getMaxWidth({ left: 0, right: 100 })).toBe("61px");
    });

    test("a zero-width area yields 0px rather than NaN", () => {
        expect(getMaxWidth({ left: 50, right: 50 })).toBe("0px");
    });
});

describe("getElementOptions — per-mode element styling", () => {
    test("bar mode sets a hairline border", () => {
        expect(getElementOptions("bar", false)).toEqual({
            bar: { borderWidth: 1 },
        });
    });

    test("line mode fills only when stacked", () => {
        expect(getElementOptions("line", true)).toEqual({
            line: { fill: true, tension: 0 },
        });
        expect(getElementOptions("line", false)).toEqual({
            line: { fill: false, tension: 0 },
        });
    });

    test("scatter mode sets point radii and ignores stacked", () => {
        const stacked = getElementOptions("scatter", true);
        expect(stacked).toEqual({ point: { radius: 5, hoverRadius: 8 } });
        expect(getElementOptions("scatter", false)).toEqual(stacked);
    });

    test("a mode with no element styling yields an empty object", () => {
        expect(getElementOptions("pie", false)).toEqual({});
    });
});

describe("getAnimationOptions — staggered entry animation", () => {
    test("pie animates its offset only, with no duration or delay", () => {
        const options = getAnimationOptions("pie", 10);
        expect(options).toEqual({ offset: { duration: 200 } });
    });

    test("bar staggers each point across a fixed 350ms budget", () => {
        const { delay } = getAnimationOptions("bar", 10);
        expect(delay({ dataIndex: 0 })).toBe(0);
        expect(delay({ dataIndex: 4 })).toBe(140);
        const denser = getAnimationOptions("bar", 35).delay;
        expect(denser({ dataIndex: 4 })).toBe(40);
    });

    test("the stagger is a one-shot: onComplete latches it off", () => {
        const options = getAnimationOptions("line", 10);
        expect(options.delay({ dataIndex: 4 })).toBe(140);
        options.onComplete();
        expect(options.delay({ dataIndex: 4 })).toBe(0);
    });

    test("no labels means no stagger rather than a division by zero", () => {
        const { delay } = getAnimationOptions("bar", 0);
        expect(delay({ dataIndex: 4 })).toBe(0);
    });

    test("a mode outside bar/line/scatter animates without staggering", () => {
        const options = getAnimationOptions("radar", 10);
        expect(options.duration).toBe(600);
        expect(options.delay({ dataIndex: 4 })).toBe(0);
    });
});
