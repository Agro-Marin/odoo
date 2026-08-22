// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";
import { makeOverlayPresenter } from "@web/ui/overlay/presenter";
import { Popover } from "@web/ui/popover/popover";

/**
 * @typedef {{
 * animation?: Boolean;
 * arrow?: Boolean;
 * closeOnClickAway?: boolean | ((target: HTMLElement) => boolean);
 * closeOnEscape?: boolean;
 * env?: object;
 * fixedPosition?: boolean;
 * onClose?: (removeParams?: any) => void;
 * onPositioned?: import("@web/core/position/position_hook").UsePositionOptions["onPositioned"];
 * class?: string;
 * role?: string;
 * id?: string;
 * position?: import("@web/core/position/position_hook").UsePositionOptions["position"];
 * ref?: Function;
 * extendedFlipping?: boolean;
 * holdOnHover?: boolean;
 * setActiveElement?: boolean;
 * sequence?: number;
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
            scope: "popover",
            toProps: (options, target) => ({
                target,
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
