// @ts-check
/** @odoo-module native */

/** @module @web/views/view_button/multi_record_view_button */

import { ViewButton } from "./view_button.js";

export class MultiRecordViewButton extends ViewButton {
    static props = {
        ...ViewButton.props,
        list: { type: Object },
        domain: { type: Array, optional: true },
    };

    /**
     * @param {MouseEvent} ev
     * @param {boolean} [newWindow]
     */
    async onClick(ev, newWindow) {
        const { list } = this.props;
        const resIds = await list.getResIds(true);
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
            beforeExecute: () => this.dropdownControl.close(),
            newWindow,
        });
    }
}
