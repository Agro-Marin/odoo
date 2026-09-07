import { models } from "@web/../tests/web_test_helpers";

export class PhoneNumber extends models.ServerModel {
    _name = "phone.number";

    _load_pos_data_fields() {
        return ["id", "number", "type", "sanitized", "primary", "sequence", "label"];
    }

    _records = [];
}
