// @ts-check
/** @odoo-module native */

/** @module @web/components/transition - CSS transition helpers for mount/unmount animations with configurable class names */

import {
    Component,
    onWillDestroy,
    onWillUpdateProps,
    status,
    useComponent,
    useEffect,
    useState,
    xml,
} from "@odoo/owl";
// Allows to disable transitions globally, useful for testing (and maybe for
// a reduced motion setting in the future?)
import { browser } from "@web/core/browser/browser";
export const config = {
    disabled: false,
};
/**
 * Creates a transition to be used within the current component. Usage:
 *  --- in JS:
 *  this.transition = useTransition({ name: "myClass" });
 *  --- in XML:
 *  <div t-if="transition.shouldMount" t-att-class="transition.class"/>
 *
 * @param {Object} options
 * @param {string} options.name the prefix to use for the transition classes
 * @param {boolean} [options.initialVisibility=true] whether to start the
 *  transition in the on or off state
 * @param {boolean} [options.immediate=false] (only relevant when initialVisibility
 *  is true) set to true to animate initially. By default, there's no animation
 *  if the element is initially visible.
 * @param {number} [options.leaveDuration] the leaveDuration of the transition
 * @param {Function} [options.onLeave] a function that will be called when the
 *  element will be removed in the next render cycle
 * @returns {{ shouldMount: boolean, className: string, stage: string }} an object
 *  containing fields that indicate whether an element on which the transition is
 *  applied should be mounted and the class string that should be put on it
 */
export function useTransition({
    name,
    initialVisibility = true,
    immediate = false,
    leaveDuration = 500,
    onLeave = () => {},
}) {
    const component = useComponent();
    const state = useState({
        shouldMount: initialVisibility,
        stage: initialVisibility ? "enter" : "leave",
    });

    if (config.disabled) {
        return {
            get shouldMount() {
                return state.shouldMount;
            },
            set shouldMount(val) {
                // No transition to animate, but keep the onLeave contract
                // symmetric with the animated path: fire it (synchronously)
                // whenever the element goes from mounted to unmounted.
                if (state.shouldMount && !val) {
                    onLeave();
                }
                state.shouldMount = val;
            },
            get className() {
                return `${name} ${name}-enter-active`;
            },
            get stage() {
                return "enter-active";
            },
        };
    }
    // Mount in "enter" state first so the transition fires when we switch to
    // enter-active on the next patch (via onNextPatch).
    let onNextPatch = null;
    useEffect(() => {
        if (onNextPatch) {
            onNextPatch();
            onNextPatch = null;
        }
    });

    let prevState, timer;
    // Clear any pending leave timer so onLeave never fires against a
    // destroyed component.
    onWillDestroy(() => browser.clearTimeout(timer));
    const transition = {
        get shouldMount() {
            return state.shouldMount;
        },
        set shouldMount(newState) {
            if (newState === prevState) {
                return;
            }
            browser.clearTimeout(timer);
            prevState = newState;
            // when true - transition from enter to enter-active
            // when false - transition from enter-active to leave, unmount after leaveDuration
            if (newState) {
                if (status(component) === "mounted" || immediate) {
                    state.stage = "enter";
                    // force a render here so that we get a patch even if the state didn't change
                    component.render();
                    onNextPatch = () => {
                        state.stage = "enter-active";
                    };
                } else {
                    state.stage = "enter-active";
                }
                state.shouldMount = true;
            } else {
                state.stage = "leave";
                // Only schedule unmount/onLeave when actually mounted, else the
                // initial `shouldMount = initialVisibility` (false) would
                // spuriously fire onLeave for an element never shown.
                if (state.shouldMount) {
                    timer = browser.setTimeout(() => {
                        state.shouldMount = false;
                        onLeave();
                    }, leaveDuration);
                }
            }
        },
        get className() {
            return `${name} ${name}-${state.stage}`;
        },
        get stage() {
            return state.stage;
        },
    };
    transition.shouldMount = initialVisibility;
    return transition;
}

/**
 * HOC version of useTransition for its default slot. Unlike the hook, it can
 * be spawned during render (e.g. in a t-foreach) without knowing at setup
 * time how many transitions are needed.
 *
 * @see useTransition
 */
export class Transition extends Component {
    static template = xml`<t t-slot="default" t-if="transition.shouldMount" className="transition.className"/>`;
    static props = {
        name: String,
        visible: { type: Boolean, optional: true },
        immediate: { type: Boolean, optional: true },
        leaveDuration: { type: Number, optional: true },
        onLeave: { type: Function, optional: true },
        slots: Object,
    };

    setup() {
        const { immediate, visible, leaveDuration, name, onLeave } = this.props;
        this.transition = useTransition({
            initialVisibility: visible,
            immediate,
            leaveDuration,
            name,
            onLeave,
        });
        onWillUpdateProps(({ visible = true }) => {
            this.transition.shouldMount = visible;
        });
    }
}
