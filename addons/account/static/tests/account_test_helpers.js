import { mailModels } from "@mail/../tests/mail_test_helpers";
import { defineModels } from "@web/../tests/web_test_helpers";

import { AccountMove } from "./mock_server/mock_models/account_move.js";
import { AccountMoveLine } from "./mock_server/mock_models/account_move_line.js";

export const accountModels = {
    AccountMove,
    AccountMoveLine,
};

export function defineAccountModels() {
    return defineModels({ ...mailModels, ...accountModels });
}
