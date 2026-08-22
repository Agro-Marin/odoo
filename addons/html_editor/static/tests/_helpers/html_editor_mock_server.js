import { beforeEach } from "@odoo/hoot";
import { onRpc } from "@web/../tests/web_test_helpers";

beforeEach(
    () => onRpc("res.lang", "get_installed", () => [["en_US", "English (US)"]]),
    { global: true },
);
