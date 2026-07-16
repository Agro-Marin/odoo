/** @odoo-module native */
import { registry } from "@web/core/registry";

import { SearchModal } from "./search_modal.js";

const SearchModalEdit = (I) =>
    class extends I {
        dynamicContent = {
            _root: {
                "t-on-show.bs.modal.prevent": () => {},
            },
        };
    };

registry.category("public.interactions.edit").add("website.search_modal", {
    Interaction: SearchModal,
    mixin: SearchModalEdit,
});
