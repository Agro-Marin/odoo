/** @odoo-module native */
import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

export class PortalSearchPanel extends Interaction {
    static selector = ".o_portal_search_panel";
    dynamicContent = {
        ".dropdown-item": {
            "t-on-click.prevent.withTarget": this.onDropdownItemClick,
        },
        _root: {
            "t-on-submit.prevent": this.search,
        },
    };

    setup() {
        this.adaptSearchLabel(this.el.querySelector(".dropdown-item.active"));
    }

    adaptSearchLabel(elem) {
        if (!elem) {
            return;
        }
        const labelEl = elem.cloneNode(true);
        labelEl.querySelector("span.nolabel")?.remove();
        this.el
            .querySelector("input[name=search]")
            ?.setAttribute("placeholder", labelEl.textContent.trim());
    }

    search() {
        const url = new URL(window.location);
        url.searchParams.set(
            "search_in",
            this.el
                .querySelector(".dropdown-item.active")
                ?.getAttribute("href")
                ?.replace("#", "") || "",
        );
        url.searchParams.set(
            "search",
            this.el.querySelector("input[name=search]")?.value || "",
        );
        url.pathname = url.pathname.replace(/\/page\/\d+\/?$/, "");
        window.location.href = url.toString();
    }

    onDropdownItemClick(ev, currentTargetEl) {
        currentTargetEl
            .closest(".dropdown-menu")
            .querySelector(".dropdown-item.active")
            ?.classList.remove("active");
        currentTargetEl.classList.add("active");

        this.adaptSearchLabel(currentTargetEl);
    }
}

registry.category("public.interactions").add("portal.portal_search_panel", PortalSearchPanel);
