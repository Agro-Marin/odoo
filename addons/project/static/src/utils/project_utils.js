/** @odoo-module native */
import { useEffect } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";

export const STATUS_COLORS = {
    on_track: 20,
    at_risk: 22,
    off_track: 23,
    on_hold: 21,
    done: 24,
};

export const STATUS_COLOR_PREFIX = "o_status_bubble mx-0 o_color_bubble_";

const SHOW_SUBTASKS_STORAGE_KEY = "showSubtasks";

export function getShowSubtasks() {
    try {
        return Boolean(
            JSON.parse(browser.localStorage.getItem(SHOW_SUBTASKS_STORAGE_KEY)),
        );
    } catch {
        return false;
    }
}

export function setShowSubtasks(value) {
    browser.localStorage.setItem(SHOW_SUBTASKS_STORAGE_KEY, Boolean(value));
}

/** @param {{ el: HTMLElement | null }} rootRef */
export function useFocusTitle(rootRef) {
    useEffect(
        (el) => {
            el?.querySelector("#name_0")?.focus();
        },
        () => [rootRef.el],
    );
}
