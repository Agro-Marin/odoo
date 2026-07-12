import { beforeEach } from "@odoo/hoot";
import { onRpc } from "@web/../tests/web_test_helpers";

// Register inside a global `beforeEach` (not module top-level) so the route is
// applied before every test under native ESM. See the same pattern in other
// `*_mock_server.js` files.
beforeEach(
    () => onRpc("res.lang", "get_installed", () => [["en_US", "English (US)"]]),
    { global: true }
);
