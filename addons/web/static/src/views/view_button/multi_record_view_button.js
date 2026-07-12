// @ts-check
/** @odoo-module native */

/** @module @web/views/view_button/multi_record_view_button - ViewButton variant for list/kanban headers that operates on multiple selected records */

import { ViewButton } from "./view_button.js";

/** ViewButton variant for list/kanban headers that operates on multiple selected records at once. */
export class MultiRecordViewButton extends ViewButton {
    // Object-merge (not array-spread) now that ViewButton.props is a shape.
    static props = {
        ...ViewButton.props,
        list: { type: Object },
        domain: { type: Array, optional: true },
    };

    /**
     * Resolve all selected record IDs from the list and inject active_domain/active_ids
     * into the button context before delegating to the environment handler.
     * @param {MouseEvent} ev
     * @param {boolean} [newWindow]
     */
    async onClick(ev, newWindow) {
        const { list } = this.props;
        const resIds = await list.getResIds(true);
        // Clone instead of mutating this.props.clickParams: it aliases the
        // parse-once descriptor in archInfo.headerButtons, shared across this
        // view's renders. Writing buttonContext onto it violates OWL prop
        // immutability and leaves stale active_ids on the shared object.
        const clickParams = {
            ...this.props.clickParams,
            buttonContext: {
                active_domain: this.props.domain,
                active_ids: resIds,
                active_model: list.resModel,
            },
        };

        return this.env.onClickViewButton({
            clickParams,
            getResParams: () => ({
                context: list.context,
                evalContext: list.evalContext,
                resModel: list.resModel,
                resIds,
            }),
            // Mirror ViewButton.onClick: close the enclosing dropdown before the
            // action runs, so a header button placed in a dropdown doesn't
            // execute with the menu left open.
            beforeExecute: () => this.dropdownControl.close(),
            newWindow,
        });
    }
}
