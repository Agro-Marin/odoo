// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";
import { BottomSheet } from "@web/ui/bottom_sheet/bottom_sheet";
import { makeOverlayPresenter } from "@web/ui/overlay/presenter";

/**
 * @typedef {import("@web/ui/popover/popover_service").PopoverServiceAddOptions & {
 * onBack?: () => void;
 * preventDismissOnContentScroll?: boolean;
 * }} BottomSheetServiceAddOptions
 * @typedef {ReturnType<bottomSheetService["start"]>["add"]} BottomSheetServiceAddFunction
 */

const bottomSheetService = {
    dependencies: ["overlay"],
    /**
     * @param {import("@web/env").OdooEnv} _
     * @param {{ overlay: any }} services
     */
    start(_, { overlay }) {
        let openCount = 0;

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
            scope: "bottom_sheet",
            toProps: (options) => ({
                onBack: options.onBack,
                preventDismissOnContentScroll: options.preventDismissOnContentScroll,
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

        return {
            add,
            destroy() {
                openCount = 0;
                syncBodyClasses();
            },
        };
    },
};

registry.category("services").add("bottom_sheet", bottomSheetService);
