// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { localization } from "@web/core/l10n/localization";

describe.current.tags("headless");

test("accessing a missing localization parameter throws a helpful error", () => {
    expect(() => localization.notALocalizationParameter).toThrow(
        /could not access localization parameter "notALocalizationParameter"/,
    );
});

test("set parameters are readable", () => {
    patchWithCleanup(localization, { dateFormat: "MM/dd/yyyy" });
    expect(localization.dateFormat).toBe("MM/dd/yyyy");
});

test("protocol probes and symbols do not throw", () => {
    // Inspecting the object while debugging (JSON.stringify, devtools
    // formatters, assertion libraries) must not raise: symbols and the
    // well-known protocol keys pass through.
    expect(() => JSON.stringify(localization)).not.toThrow();
    expect(localization[Symbol.toStringTag]).toBe(undefined);
    expect(localization[Symbol.toPrimitive]).toBe(undefined);
    expect(localization.then).toBe(undefined);
    expect(localization.constructor).toBe(Object);
    expect(localization.inspect).toBe(undefined);
});
