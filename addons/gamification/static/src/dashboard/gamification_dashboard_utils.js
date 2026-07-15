/** @odoo-module native */

// Pure presentation helpers for the gamification dashboard and notification
// service.  Kept free of component state so they can be unit-tested in
// isolation (see ../../tests/gamification_dashboard_utils.test.js).

// A streak burning for this many days is "hot" (gold flame); half as many is
// "warm" (green flame).  Below that it is a muted ember.
export const STREAK_HOT_DAYS = 30;
export const STREAK_WARM_DAYS = 7;

const BADGE_LEVEL_CLASS = {
    gold: "text-warning",
    silver: "text-muted",
    bronze: "text-danger",
};

const TREND_ICON = {
    up: "fa-arrow-up text-success",
    down: "fa-arrow-down text-danger",
    flat: "fa-minus text-muted",
    new: "fa-plus text-info",
};

// Achievement rarity → Bootstrap contextual badge background.
const RARITY_BADGE_CLASS = {
    legendary: "bg-success",
    epic: "bg-warning",
    rare: "bg-info",
    common: "bg-secondary",
};

// Gamification bus event type → Font Awesome glyph (without the leading "fa").
const NOTIFICATION_ICON = {
    badge: "fa-certificate",
    streak: "fa-fire",
    level_up: "fa-arrow-up",
    achievement: "fa-trophy",
};

export function getBadgeLevelClass(level) {
    return BADGE_LEVEL_CLASS[level] || "";
}

export function getTrendIcon(trend) {
    return TREND_ICON[trend] || TREND_ICON.flat;
}

export function getRarityBadgeClass(rarity) {
    return RARITY_BADGE_CLASS[rarity] || RARITY_BADGE_CLASS.common;
}

export function getNotificationIcon(type) {
    return NOTIFICATION_ICON[type] || "fa-star";
}

export function getStreakIcon(streak) {
    if (streak.state === "broken") {
        return "fa-heart-o text-danger";
    }
    if (streak.current_count >= STREAK_HOT_DAYS) {
        return "fa-fire text-warning";
    }
    if (streak.current_count >= STREAK_WARM_DAYS) {
        return "fa-fire text-success";
    }
    return "fa-fire text-muted";
}
