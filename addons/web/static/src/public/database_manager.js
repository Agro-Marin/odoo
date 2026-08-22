// @ts-check
/** @odoo-module native */

import { setupDatabaseManager } from "./database_manager_page.js";

// @ts-ignore — bootstrap is exposed at runtime by the page's importmap, but its types are not part of this fork's npm tree
import { Modal } from "bootstrap";

const start = () =>
    setupDatabaseManager(document.body, {
        getModal: (el) => Modal.getOrCreateInstance(el),
    });

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
} else {
    start();
}
