import { models } from "@web/../tests/web_test_helpers";

export class AccountJournal extends models.ServerModel {
    _name = "account.journal";

    is_sample_action_available() {
        return false;
    }
}
