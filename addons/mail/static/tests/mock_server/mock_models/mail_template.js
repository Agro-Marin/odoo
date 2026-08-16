import { fields, models } from "@web/../tests/web_test_helpers";

export class MailTemplate extends models.ServerModel {
    _name = "mail.template";
    name = fields.Char();
}
