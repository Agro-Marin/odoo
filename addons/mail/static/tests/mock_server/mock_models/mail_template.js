import { fields, models } from "@web/../tests/web_test_helpers";

export class MailTemplate extends models.ServerModel {
    _name = "mail.template";
    // The fork's real `mail.template.name` is a non-stored *related* field
    // (`document_template_id.name`, from the document-template refactor), which
    // `/web/model/get_definitions` omits (its base relation is not co-fetched)
    // and which — being non-stored — the mock server could not persist on
    // write anyway. Declare it as a plain stored Char so tests can create and
    // read templates by name.
    name = fields.Char();
}
