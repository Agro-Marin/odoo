/** @odoo-module native */
import { describe, expect, test } from "@odoo/hoot";
import {
    STREAK_HOT_DAYS,
    STREAK_WARM_DAYS,
    getBadgeLevelClass,
    getNotificationIcon,
    getRarityBadgeClass,
    getStreakIcon,
    getTrendIcon,
} from "@gamification/dashboard/gamification_dashboard_utils";

describe.current.tags("headless");

describe("getBadgeLevelClass", () => {
    test("maps known levels", () => {
        expect(getBadgeLevelClass("gold")).toBe("text-warning");
        expect(getBadgeLevelClass("silver")).toBe("text-muted");
        expect(getBadgeLevelClass("bronze")).toBe("text-danger");
    });
    test("returns empty string for unknown / falsy level", () => {
        expect(getBadgeLevelClass("platinum")).toBe("");
        expect(getBadgeLevelClass(undefined)).toBe("");
        expect(getBadgeLevelClass(false)).toBe("");
    });
});

describe("getTrendIcon", () => {
    test("maps known trends", () => {
        expect(getTrendIcon("up")).toBe("fa-arrow-up text-success");
        expect(getTrendIcon("down")).toBe("fa-arrow-down text-danger");
        expect(getTrendIcon("flat")).toBe("fa-minus text-muted");
        expect(getTrendIcon("new")).toBe("fa-plus text-info");
    });
    test("falls back to flat for unknown trend", () => {
        expect(getTrendIcon("sideways")).toBe("fa-minus text-muted");
        expect(getTrendIcon(undefined)).toBe("fa-minus text-muted");
    });
});

describe("getRarityBadgeClass", () => {
    test("maps known rarities", () => {
        expect(getRarityBadgeClass("legendary")).toBe("bg-success");
        expect(getRarityBadgeClass("epic")).toBe("bg-warning");
        expect(getRarityBadgeClass("rare")).toBe("bg-info");
        expect(getRarityBadgeClass("common")).toBe("bg-secondary");
    });
    test("falls back to common styling for unknown rarity", () => {
        expect(getRarityBadgeClass("mythic")).toBe("bg-secondary");
        expect(getRarityBadgeClass(undefined)).toBe("bg-secondary");
    });
});

describe("getNotificationIcon", () => {
    test("maps known event types", () => {
        expect(getNotificationIcon("badge")).toBe("fa-certificate");
        expect(getNotificationIcon("streak")).toBe("fa-fire");
        expect(getNotificationIcon("level_up")).toBe("fa-arrow-up");
        expect(getNotificationIcon("achievement")).toBe("fa-trophy");
    });
    test("falls back to a star for unknown type", () => {
        expect(getNotificationIcon("mystery")).toBe("fa-star");
        expect(getNotificationIcon(undefined)).toBe("fa-star");
    });
});

describe("getStreakIcon", () => {
    test("broken streak shows a broken heart regardless of count", () => {
        expect(getStreakIcon({ state: "broken", current_count: 999 })).toBe(
            "fa-heart-o text-danger",
        );
    });
    test("hot streak at/over the hot threshold", () => {
        expect(getStreakIcon({ state: "active", current_count: STREAK_HOT_DAYS })).toBe(
            "fa-fire text-warning",
        );
    });
    test("warm streak between warm and hot thresholds", () => {
        expect(
            getStreakIcon({ state: "active", current_count: STREAK_WARM_DAYS }),
        ).toBe("fa-fire text-success");
        expect(
            getStreakIcon({ state: "active", current_count: STREAK_HOT_DAYS - 1 }),
        ).toBe("fa-fire text-success");
    });
    test("cold streak below the warm threshold", () => {
        expect(
            getStreakIcon({ state: "active", current_count: STREAK_WARM_DAYS - 1 }),
        ).toBe("fa-fire text-muted");
        expect(getStreakIcon({ state: "active", current_count: 0 })).toBe(
            "fa-fire text-muted",
        );
    });
});
