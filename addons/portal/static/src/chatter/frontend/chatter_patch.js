/** @odoo-module native */
import { Chatter } from "@mail/chatter/web_portal/chatter";

import { patch } from "@web/core/utils/patch";
import { useRef, useEffect } from "@odoo/owl";

patch(Chatter.prototype, {
    setup() {
        super.setup(...arguments);
        this.topRef = useRef("top");
        // Keep the composer position under the page header on scrolling unless
        // the header is on the side. Creating the observer and calling observe()
        // must happen in the SAME effect: the previous split (create in
        // onWillPatch, observe in a useEffect keyed on topRef.el) re-created the
        // observer on every re-render but only observed on the first appearance
        // of the top element — so any later re-render (posting a message,
        // opening the composer, searching, ...) replaced the live observer with
        // an idle one and silently broke the sticky padding. Keyed on topRef.el
        // (recreate when the top element appears/changes) and twoColumns (layout
        // switch), the observer is created once, observes, and its cleanup
        // disconnects it — surviving unrelated re-renders untouched.
        useEffect(
            (topEl) => {
                if (!topEl) {
                    return;
                }
                const headerEl = document.querySelector("#wrapwrap header");
                if (this.props.twoColumns || !headerEl || headerEl.matches(".o_header_sidebar")) {
                    return;
                }
                const paddingTop = headerEl.getBoundingClientRect().height + 15 + "px";
                const observer = new IntersectionObserver(
                    ([e]) =>
                        (e.target.style.paddingTop =
                            e.target.getBoundingClientRect().y < 1 ? paddingTop : "20px"),
                    { threshold: [1] }
                );
                observer.observe(topEl);
                return () => observer.disconnect();
            },
            () => [this.topRef.el, this.props.twoColumns]
        );
    },
});
