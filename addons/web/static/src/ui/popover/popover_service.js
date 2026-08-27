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
 * @typedef {PopoverService["add"]} PopoverServiceAddFunction
 */

class PopoverService {
    /**
     * @param {{ overlay: any }} services
     */
    constructor({ overlay }) {
        this.present = makeOverlayPresenter({
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
    }

    /**
     * @param {HTMLElement} target
     * @param {import("@odoo/owl").ComponentConstructor} component
     * @param {object} [props]
     * @param {PopoverServiceAddOptions} [options]
     * @returns {(removeParams?: any) => Promise<void>}
     */
    add(target, component, props = {}, options = {}) {
        return this.present(target, component, props, options);
    }
}

export const popoverService = {
    dependencies: ["overlay"],
    /**
     * @param {import("@web/env").OdooEnv} _
     * @param {{ overlay: any }} services
     * @returns {PopoverService}
     */
    start(_, services) {
        return new PopoverService(services);
    },
};

registry.category("services").add("popover", popoverService);
