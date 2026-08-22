/** @odoo-module native */
import { Chatter } from "@mail/chatter/web_portal/chatter";

import { patch } from "@web/core/utils/patch";
import { useRef, useEffect } from "@odoo/owl";

patch(Chatter.prototype, {
    setup() {
        super.setup(...arguments);
        this.topRef = useRef("top");
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
