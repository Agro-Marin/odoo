// @ts-check
/** @odoo-module native */

/** @module @web/ui/popover/popover_service */

import { registry } from "@web/core/registry";
import {
    declarePresenterOptions,
    makeOverlayPresenter,
} from "@web/ui/overlay/presenter";
import { Popover } from "@web/ui/popover/popover";

declarePresenterOptions([
    "animation",
    "arrow",
    "extendedFlipping",
    "fixedPosition",
    "holdOnHover",
    "onPositioned",
    "position",
]);

/**
 * `closeOnClickAway` is handed the clicked node by a popover, but a bottom
 * sheet always reports its own backdrop: the backdrop covers everything outside
 * the sheet, so no other node is ever the target. A predicate that inspects
 * what was clicked therefore only discriminates on the popover side. Decide
 * with the argument by all means -- just do not rely on it to keep a sheet
 * open, because on that side it cannot.
 *
 * @typedef {{
 *   animation?: Boolean;
 *   arrow?: Boolean;
 *   closeOnClickAway?: boolean | ((target: HTMLElement) => boolean);
 *   closeOnEscape?: boolean;
 *   env?: object;
 *   fixedPosition?: boolean;
 *   onClose?: (removeParams?: any) => void;
 *   onPositioned?: import("@web/core/position/position_hook").UsePositionOptions["onPositioned"];
 *   popoverClass?: string;
 *   role?: string;
 *   id?: string;
 *   position?: import("@web/core/position/position_hook").UsePositionOptions["position"];
 *   ref?: Function;
 *   extendedFlipping?: boolean;
 *   holdOnHover?: boolean;
 *   setActiveElement?: boolean;
 *   sequence?: number;
 * }} PopoverServiceAddOptions
 * @typedef {ReturnType<popoverService["start"]>["add"]} PopoverServiceAddFunction
 */

export const popoverService = {
    dependencies: ["overlay"],
    /**
     * @param {import("@web/env").OdooEnv} _
     * @param {{ overlay: any }} services
     */
    start(_, { overlay }) {
        /**
         * @type {(target: HTMLElement, component: import("@odoo/owl").ComponentConstructor, props?: object, options?: PopoverServiceAddOptions) => (removeParams?: any) => Promise<void>}
         */
        const add = makeOverlayPresenter({
            overlay,
            component: Popover,
            toProps: (options) => ({
                animation: options.animation,
                arrow: options.arrow,
                extendedFlipping: options.extendedFlipping,
                fixedPosition: options.fixedPosition,
                holdOnHover: options.holdOnHover,
                onPositioned: options.onPositioned,
                position: options.position,
            }),
        });

        return { add };
    },
};

registry.category("services").add("popover", popoverService);
