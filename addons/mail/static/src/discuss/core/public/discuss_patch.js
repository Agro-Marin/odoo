// @ts-check
/** @odoo-module native */
import { Discuss } from "@mail/core/public_web/discuss";
import { useService } from "@web/core/utils/hooks";
import { useLayoutEffect } from "@web/core/utils/layout_effect";
import { patch } from "@web/core/utils/patch";
patch(Discuss.prototype, {
    setup() {
        super.setup();
        this.title = useService("title");
        useLayoutEffect(
            /** @param {string|undefined} threadName */
            (threadName) => {
                if (threadName) {
                    this.title.setParts({ action: threadName });
                }
            },
            () => [this.thread?.displayName],
        );
    },
});
