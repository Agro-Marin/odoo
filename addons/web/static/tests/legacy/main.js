// @ts-check

/** @odoo-module alias=@web/../tests/main default=false */

import { setupQUnit } from "./qunit.js";
import { setupTests } from "./setup.js";

(async () => {
    setupQUnit();
    await setupTests();
    QUnit.start();
})();
