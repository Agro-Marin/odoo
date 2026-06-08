// @ts-check

import { after } from "@odoo/hoot";
import {
    loadLanguages,
    translatedTerms,
    translatedTermsGlobal,
    translationLoaded,
} from "@web/core/l10n/translation";

import { serverState } from "./mock_server_state.hoot.js";
import { patchWithCleanup } from "./patch_test_helpers.js";

/**
 * @param {Record<string, string>} languages
 */
export function installLanguages(languages) {
    serverState.multiLang = true;
    patchWithCleanup(loadLanguages, {
        installedLanguages: Object.entries(languages),
    });
}

export function allowTranslations() {
    translatedTerms[translationLoaded] = true;
    after(() => {
        // Keep the flag truthy after teardown — the bundle-level
        // ``setupTestEnvironment`` sets it once at module load and the
        // rest of the suite (any plugin building a template with a
        // lazy ``_t(…)`` substitution) expects it to stay truthy.
        // Resetting to ``false`` here would re-introduce the failure
        // mode that the fix in ``env_test_helpers.js`` addresses.
        translatedTerms[translationLoaded] = true;
    });
}

/**
 * @param {Record<string, Record<string, string>>} [terms]
 */
export function patchTranslations(terms = {}) {
    allowTranslations();
    for (const addonName in terms) {
        if (!(addonName in translatedTerms)) {
            patchWithCleanup(translatedTerms, { [addonName]: {} });
        }
        patchWithCleanup(translatedTerms[addonName], terms[addonName]);
        patchWithCleanup(translatedTermsGlobal, terms[addonName]);
    }
}
