/** @odoo-module native */
import hoot from "@odoo/hoot-dom";
import { pick } from "@web/core/utils/collections/objects";
import { session } from "@web/session";
import { utils } from "@web/ui/viewport";

/**
 * @typedef TourStep
 * @property {"enterprise"|"community"|"mobile"|"desktop"|HootSelector[][]} isActive
 * @property {string} [id]
 * @property {HootSelector} trigger
 * @property {string} [content]
 * @property {"top" | "bottom" | "left" | "right"} [position]
 * @property {RunCommand} [run]
 * @property {number} [timeout]
 */
export class TourStep {
    constructor(data, tour) {
        Object.assign(this, data);
        this.tour = tour;
    }

    get active() {
        this.checkHasTour();
        const mode = this.tour.mode;
        const isSmall = utils.isSmall();
        const standardKeyWords = [
            "enterprise",
            "community",
            "mobile",
            "desktop",
            "auto",
            "manual",
        ];
        const isActiveArray = Array.isArray(this.isActive) ? this.isActive : [];
        if (isActiveArray.length === 0) {
            return true;
        }
        const selectors = isActiveArray.filter(
            (key) => !standardKeyWords.includes(key),
        );
        if (selectors.length) {
            for (const selector of selectors) {
                const el = hoot.queryFirst(selector);
                if (!el) {
                    return false;
                }
            }
        }
        const checkMode =
            isActiveArray.includes(mode) ||
            (!isActiveArray.includes("manual") && !isActiveArray.includes("auto"));
        const edition =
            (session.server_version_info || "").at(-1) === "e"
                ? "enterprise"
                : "community";
        const checkEdition =
            isActiveArray.includes(edition) ||
            (!isActiveArray.includes("enterprise") &&
                !isActiveArray.includes("community"));
        const onlyForMobile = isActiveArray.includes("mobile") && isSmall;
        const onlyForDesktop = isActiveArray.includes("desktop") && !isSmall;
        const checkDevice =
            onlyForMobile ||
            onlyForDesktop ||
            (!isActiveArray.includes("mobile") && !isActiveArray.includes("desktop"));
        return checkEdition && checkDevice && checkMode;
    }

    checkHasTour() {
        if (!this.tour) {
            throw new Error(`TourStep instance must have a tour`);
        }
    }

    get describeMe() {
        this.checkHasTour();
        return (
            `[${this.index + 1}/${this.tour.steps.length}] Tour ${this.tour.name} → Step ` +
            (this.content ? `${this.content} (trigger: ${this.trigger})` : this.trigger)
        );
    }

    get stringify() {
        return (
            JSON.stringify(
                pick(
                    this,
                    "isActive",
                    "content",
                    "trigger",
                    "run",
                    "tooltipPosition",
                    "timeout",
                    "expectUnloadPage",
                ),
                (_key, value) => {
                    if (typeof value === "function") {
                        return "[function]";
                    } else {
                        return value;
                    }
                },
                2,
            ) + ","
        );
    }
}
