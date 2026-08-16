/** @odoo-module native */
import { Call } from "@mail/discuss/call/common/call";
import { Meeting } from "@mail/discuss/call/common/meeting";
import { registry } from "@web/core/registry";
const callComponentsRegistry = registry.category("discuss.call/components");

callComponentsRegistry.add("Call", Call).add("Meeting", Meeting);
