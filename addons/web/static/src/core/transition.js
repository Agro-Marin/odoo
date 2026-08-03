// @ts-check
/** @odoo-module native */

/** @module @web/core/transition */

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
import { browser } from "@web/core/browser/browser";
export const config = {
    disabled: false,
};
/**
 * `initialVisibility` and `immediate` describe the first mount, so reading them
 * once is what they mean. The other three describe every transition this hook
 * will ever run, and a caller is free to hand them over behind getters -- which
 * is what `Transition` does with its props. Destructuring them here would have
 * frozen whatever they happened to be during setup.
 *
 * @param {Object} options
 * @param {string} options.name
 * @param {boolean} [options.initialVisibility=true]
 * @param {boolean} [options.immediate=false]
 * @param {number} [options.leaveDuration]
 * @param {Function} [options.onLeave]
 * @returns {{ shouldMount: boolean, className: string, stage: string }}
 */
export function useTransition(options) {
    const { initialVisibility = true, immediate = false } = options;
    const name = () => options.name;
    const leaveDuration = () => options.leaveDuration ?? 500;
    const onLeave = () => options.onLeave?.();
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
                if (state.shouldMount && !val) {
                    onLeave();
                }
                state.shouldMount = val;
            },
            get className() {
                return `${name()} ${name()}-enter-active`;
            },
            get stage() {
                return "enter-active";
            },
        };
    }
    let onNextPatch = null;
    useEffect(() => {
        if (onNextPatch) {
            onNextPatch();
            onNextPatch = null;
        }
    });

    let prevState, timer;
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
            if (newState) {
                if (status(component) === "mounted" || immediate) {
                    state.stage = "enter";
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
                if (state.shouldMount) {
                    timer = browser.setTimeout(() => {
                        state.shouldMount = false;
                        onLeave();
                    }, leaveDuration());
                }
            }
        },
        get className() {
            return `${name()} ${name()}-${state.stage}`;
        },
        get stage() {
            return state.stage;
        },
    };
    transition.shouldMount = initialVisibility;
    return transition;
}

/**
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

    /** @type {ReturnType<typeof useTransition>} */
    transition;

    setup() {
        const self = this;
        // The leave is started from onWillUpdateProps, which owl runs *before*
        // it swaps `this.props`. Reading the incoming props from there would
        // otherwise start the leave on the duration the caller just replaced.
        // Afterwards owl assigns the same object to `this.props`, so this stays
        // the current props for every later read.
        this.latestProps = this.props;
        this.transition = useTransition({
            initialVisibility: this.props.visible,
            immediate: this.props.immediate,
            get leaveDuration() {
                return self.latestProps.leaveDuration;
            },
            get name() {
                return self.latestProps.name;
            },
            get onLeave() {
                return self.latestProps.onLeave;
            },
        });
        onWillUpdateProps((nextProps) => {
            this.latestProps = nextProps;
            this.transition.shouldMount = nextProps.visible ?? true;
        });
    }
}
