/** @odoo-module native */
import { Chatter } from "@mail/chatter/web_portal/chatter";

import { patch } from "@web/core/utils/patch";
import { useRef, onWillPatch, onWillDestroy, useEffect } from "@odoo/owl";

patch(Chatter.prototype, {
    setup() {
        super.setup(...arguments);
        this.topRef = useRef("top");
        this.observer = null;
        onWillPatch(() => {
            // Disconnect any previous observer before allocating a new one —
            // onWillPatch fires on every re-render, and orphaned observers
            // keep their target references alive (memory + CPU leak).
            this.observer?.disconnect();
            this.observer = null;
            // Keep the composer position under the page header on scrolling
            // unless the header is on the side.
            const headerEl = document.querySelector("#wrapwrap header");
            if (!this.props.twoColumns && headerEl && !headerEl.matches(".o_header_sidebar")) {
                const paddingTop = headerEl.getBoundingClientRect().height + 15 + "px";
                this.observer = new IntersectionObserver(
                    ([e]) =>
                        (e.target.style.paddingTop =
                            e.target.getBoundingClientRect().y < 1 ? paddingTop : "20px"),
                    {
                        threshold: [1],
                    }
                );
            }
        });
        onWillDestroy(() => this.observer?.disconnect());
        useEffect(
            () => {
                if (this.topRef.el) {
                    this.observer?.observe(this.topRef.el);
                }
            },
            () => [this.topRef.el]
        );
    },
});
