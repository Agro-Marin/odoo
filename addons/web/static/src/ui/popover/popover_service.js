// @ts-check
/** @odoo-module native */

/** @module @web/ui/popover/popover_service - Service for programmatically attaching popover components to target elements */

import { registry } from "@web/core/registry";
import { asPredicate, makeOverlayPresenter } from "@web/ui/overlay/presenter";
import { Popover } from "@web/ui/popover/popover";

/**
 * @typedef {{
 *   animation?: Boolean;
 *   arrow?: Boolean;
 *   closeOnClickAway?: boolean | ((target: HTMLElement) => boolean);
 *   closeOnEscape?: boolean;
 *   env?: object;
 *   fixedPosition?: boolean;
 *   onClose?: () => void;
 *   onPositioned?: import("@web/core/position/position_hook").UsePositionOptions["onPositioned"];
 *   popoverClass?: string;
 *   role?: string;
 *   position?: import("@web/core/position/position_hook").UsePositionOptions["position"];
 *   ref?: Function;
 *   extendedFlipping?: boolean;
 *   holdOnHover?: boolean;
 *   setActiveElement?: boolean;
 *   sequence?: number;
 * }} PopoverServiceAddOptions
 *
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
         * Signals the manager to add a popover.
         *
         * @type {(target: HTMLElement, component: import("@odoo/owl").ComponentConstructor, props?: object, options?: PopoverServiceAddOptions) => () => void}
         */
        const add = makeOverlayPresenter({
            overlay,
            component: Popover,
            toProps: (options) => ({
                animation: options.animation,
                arrow: options.arrow,
                class: options.class ?? options.popoverClass,
                closeOnClickAway: asPredicate(options.closeOnClickAway),
                closeOnEscape: options.closeOnEscape,
                extendedFlipping: options.extendedFlipping,
                fixedPosition: options.fixedPosition,
                holdOnHover: options.holdOnHover,
                onPositioned: options.onPositioned,
                position: options.position,
                ref: options.ref,
                role: options.role,
                setActiveElement: options.setActiveElement ?? true,
            }),
        });

        return { add };
    },
};

registry.category("services").add("popover", popoverService);
