/** @odoo-module native */

import { mount, reactive } from "/web/static/lib/owl/owl.es.js";

import { Homepage } from "./Homepage.js";
import Store from "./store.js";

function createStore() {
    return reactive(new Store());
}

mount(Homepage, document.body, {
    env: {
        store: createStore(),
    },
    dev: new URLSearchParams(window.location.search).has("debug"),
});
