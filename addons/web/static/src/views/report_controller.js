// @ts-check
/** @odoo-module native */

import { Component, toRaw, useState } from "@odoo/owl";
import { useSetupAction } from "@web/core/action_hook";
import { useModelWithSampleData } from "@web/model/model";
import { standardViewProps } from "@web/views/standard_view_props";
import { useViewChassis, ViewLayout } from "@web/views/view_components";
import { computeModelOptions } from "@web/views/view_utils";

export class ReportController extends Component {
    static components = { ViewLayout };
    static props = {
        ...standardViewProps,
        Model: Function,
        modelParams: Object,
        Renderer: Function,
        buttonTemplate: String,
    };

    /** @type {any} */
    model;
    /** @type {any} */
    searchBarToggler;
    /** @type {ReturnType<typeof useViewChassis>} */
    chassis;
    /** @type {ReturnType<typeof useSetupAction>} */
    actionState;

    setup() {
        this.model = useState(
            useModelWithSampleData(
                this.props.Model,
                // The model keeps these; handing it a reactive proxy of the
                // props makes every read of metaData a subscription.
                toRaw(this.props.modelParams),
                this.modelOptions,
            ),
        );
        // Before `useSetupAction`, which needs the root ref the chassis
        // forwards: `ViewLayout` renders the view root now, so a `useRef`
        // here would resolve to nothing and scroll restoration would stop
        // silently.
        this.chassis = useViewChassis(this.chassisHooks);
        // One toggler under two names: `chassis.props` carries it to
        // `ViewLayout`, and the templates that predate ViewLayout read this.
        this.searchBarToggler = this.chassis.searchBarToggler;
        this.actionState = useSetupAction({
            rootRef: this.chassis.rootRef,
            getLocalState: () => this.getLocalState(),
            getContext: () => this.getContext(),
        });
    }

    /**
     * Hooks for {@link useViewChassis}, for a subclass whose no-content
     * condition is its own. Overriding this rather than calling
     * `useViewChassis` again matters: a second call builds a second
     * `useSearchBarToggler`, and two togglers over one search bar disagree
     * about whether it is open.
     *
     * @returns {Record<string, () => any>}
     */
    get chassisHooks() {
        return {};
    }

    /**
     * @returns {Object}
     */
    get modelOptions() {
        return /** @type {any} */ (computeModelOptions(this.env, this.props.display));
    }

    /**
     * @returns {Object}
     */
    getLocalState() {
        return { metaData: this.model.metaData };
    }

    /**
     * @returns {Object}
     */
    getContext() {
        return {};
    }
}
