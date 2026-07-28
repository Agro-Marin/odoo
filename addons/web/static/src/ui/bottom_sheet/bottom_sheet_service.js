// @ts-check
/** @odoo-module native */

/** @module @web/ui/bottom_sheet/bottom_sheet_service - Service for programmatically showing mobile bottom sheet overlays */

import { registry } from "@web/core/registry";
import { BottomSheet } from "@web/ui/bottom_sheet/bottom_sheet";
import { makeOverlayPresenter } from "@web/ui/overlay/presenter";

/**
 * Accepts the same options as the popover service — `usePopover` routes to
 * either backend from a live media query and cannot know in advance which one
 * will read the bag. Options with no meaning for a slide-up panel
 * (`position`, `arrow`, `onPositioned`, …) are accepted and ignored on
 * purpose; anything outside the shared set warns in debug mode.
 *
 * @typedef {import("@web/ui/popover/popover_service").PopoverServiceAddOptions & {
 *   onBack?: () => void;
 *   preventDismissOnContentScroll?: boolean;
 * }} BottomSheetServiceAddOptions
 *
 * @typedef {ReturnType<bottomSheetService["start"]>["add"]} BottomSheetServiceAddFunction
 */

/** Service for showing mobile-friendly bottom sheet overlays (slide-up panels). */
export const bottomSheetService = {
    dependencies: ["overlay"],
    /**
     * @param {import("@web/env").OdooEnv} _
     * @param {{ overlay: any }} services
     */
    start(_, { overlay }) {
        let openCount = 0;

        /** Body classes let the page below react to one vs. several sheets. */
        const syncBodyClasses = () => {
            document.body.classList.toggle("bottom-sheet-open", openCount > 0);
            document.body.classList.toggle("bottom-sheet-open-multiple", openCount > 1);
        };

        /**
         * @type {(target: HTMLElement, component: import("@odoo/owl").ComponentConstructor, props?: object, options?: BottomSheetServiceAddOptions) => () => void}
         */
        const add = makeOverlayPresenter({
            overlay,
            component: BottomSheet,
            toProps: (options) => ({
                class: options.class ?? options.popoverClass,
                closeOnClickAway: options.closeOnClickAway,
                onBack: options.onBack,
                preventDismissOnContentScroll: options.preventDismissOnContentScroll,
                ref: options.ref,
                role: options.role,
                setActiveElement: options.setActiveElement,
            }),
            onOpen: () => {
                openCount++;
                syncBodyClasses();
            },
            onClosed: () => {
                openCount = Math.max(0, openCount - 1);
                syncBodyClasses();
            },
        });

        return { add };
    },
};

registry.category("services").add("bottom_sheet", bottomSheetService);
