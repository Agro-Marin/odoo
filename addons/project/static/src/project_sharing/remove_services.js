/** @odoo-module native */
import { registry } from "@web/core/registry";

const servicesToRemove = ["studio", "studio_legacy", "spreadsheet"];

const servicesRegistry = registry.category("services");

export function removeServices() {
    for (const service of servicesToRemove) {
        if (servicesRegistry.contains(service)) {
            servicesRegistry.remove(service);
        }
    }
}
