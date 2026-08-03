// @ts-check
/** @odoo-module native */

/** @module @web/ui/popover/popover_service */

import { registry } from "@web/core/registry";
import {
    asPredicate,
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
                class: options.class ?? options.popoverClass,
                closeOnClickAway: asPredicate(options.closeOnClickAway),
                closeOnEscape: options.closeOnEscape,
                extendedFlipping: options.extendedFlipping,
                fixedPosition: options.fixedPosition,
                holdOnHover: options.holdOnHover,
                id: options.id,
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
