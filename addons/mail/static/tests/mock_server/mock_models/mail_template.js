import { fields, models } from "@web/../tests/web_test_helpers";

export class MailTemplate extends models.ServerModel {
    _name = "mail.template";
    // declared explicitly so tests can create and read templates by name
    name = fields.Char();
}
