import { expect, test } from "@odoo/hoot";
import {
    CUSTOMIZE_MAILING_VARIABLES,
    CUSTOMIZE_MAILING_VARIABLES_DEFAULTS,
} from "@mass_mailing/builder/plugins/customize_mailing_variables";

// A variable with no CUSTOMIZE_MAILING_VARIABLES_DEFAULTS entry silently falls
// back to "" in customize_mailing_plugin.js (`Object.values(DEFAULTS[variable]
// ?? {})[0] ?? ""`) — a legitimate no-op for properties meant to inherit the
// browser's initial value (font-weight/font-style/text-decoration-line: "" is
// "don't force it"), but a real bug for properties that need a concrete value
// to render at all (font-size, padding, background-color, border-color).
//
// These 6 keys are a confirmed pre-existing, upstream-inherited exception —
// present verbatim in the pristine `19.0` mirror branch, and already missing
// for the *base* btn-primary/btn-secondary (not just the -lg/-sm/-outline
// variants added by this fix) — so they are excluded here rather than
// "fixed": that's a distinct, out-of-scope gap, not this bug class.
const KNOWN_INTENTIONAL_GAPS = [
    "--btn-primary-font-style",
    "--btn-primary-font-weight",
    "--btn-primary-text-decoration-line",
    "--btn-secondary-font-style",
    "--btn-secondary-font-weight",
    "--btn-secondary-text-decoration-line",
];

test("every CUSTOMIZE_MAILING_VARIABLES key has a matching CUSTOMIZE_MAILING_VARIABLES_DEFAULTS entry", () => {
    const missing = Object.keys(CUSTOMIZE_MAILING_VARIABLES).filter(
        (key) =>
            !(key in CUSTOMIZE_MAILING_VARIABLES_DEFAULTS) &&
            !KNOWN_INTENTIONAL_GAPS.includes(key)
    );
    expect(missing).toEqual([]);
});
