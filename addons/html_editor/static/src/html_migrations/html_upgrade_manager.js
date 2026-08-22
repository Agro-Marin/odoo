/** @odoo-module native */
import {
    compareVersions,
    htmlEditorVersions,
    VERSION_SELECTOR,
} from "@html_editor/html_migrations/html_migrations_utils";
import { fixInvalidHTML } from "@html_editor/utils/sanitize";
import { markup } from "@odoo/owl";
import { registry } from "@web/core/registry";

export class HtmlUpgradeManager {
    constructor() {
        this.upgradeRegistry = registry.category("html_editor_upgrade");
        this.parser = new DOMParser();
        this.originalValue = undefined;
        this.upgradedValue = undefined;
        this.element = undefined;
        this.env = {};
    }

    get value() {
        return this.upgradedValue;
    }

    processForUpgrade(value, { containsComplexHTML, env } = {}) {
        this.env = env || {};
        this.containsComplexHTML = containsComplexHTML;
        const strValue = value.toString();
        if (
            strValue === this.originalValue?.toString() ||
            strValue === this.upgradedValue?.toString()
        ) {
            return this.value;
        }
        this.originalValue = value;
        this.upgradedValue = value;
        this.element = this.parser.parseFromString(fixInvalidHTML(value), "text/html")[
            this.containsComplexHTML ? "documentElement" : "body"
        ];
        const versionNode = this.element.querySelector(VERSION_SELECTOR);
        const version = versionNode?.dataset.oeVersion || "0.0";
        const VERSIONS = htmlEditorVersions();
        const currentVersion = VERSIONS.at(-1);
        if (!currentVersion || version === currentVersion) {
            return this.value;
        }
        try {
            const upgradeSequence = VERSIONS.filter(
                (subVersion) =>
                    compareVersions(subVersion, version) > 0,
            );
            this.upgradedValue = this.upgrade(upgradeSequence);
        } catch {
            // If an upgrade fails, silently continue to use the raw value.
        }
        return this.value;
    }

    upgrade(upgradeSequence) {
        for (const version of upgradeSequence) {
            const modules = this.upgradeRegistry.category(version);
            for (const [key, module] of modules.getEntries()) {
                const migrate = odoo.loader.modules.get(module).migrate;
                if (!migrate) {
                    console.error(
                        `A "${key}" migrate function could not be found at "${module}" or it did not load.`,
                    );
                }
                migrate(this.element, this.env);
            }
        }
        return markup(
            this.element[this.containsComplexHTML ? "outerHTML" : "innerHTML"],
        );
    }
}
