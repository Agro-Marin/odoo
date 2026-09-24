// @ts-check
/** @odoo-module native */

import { useViewButtonContext } from "@web/core/view_button_context_hooks";

import { ViewButton } from "./view_button.js";

export class MultiRecordViewButton extends ViewButton {
    static props = {
        ...ViewButton.props,
        list: { type: Object },
        domain: { type: Array, optional: true },
    };

    setup() {
        super.setup();
        this.viewButtonContext = useViewButtonContext();
    }

    /** @param {boolean} [newWindow] */
    async execute(newWindow) {
        const { list } = this.props;
        const resIds = await list.getResIds(true);
        const clickParams = {
            ...this.clickParams,
            buttonContext: {
                active_domain: this.props.domain,
                active_ids: resIds,
                active_model: list.resModel,
            },
        };

        return this.viewButtonContext.onClickViewButton({
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
