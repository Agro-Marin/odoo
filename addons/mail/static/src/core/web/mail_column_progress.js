import { ColumnProgress } from "@web/views/kanban/column_progress";
export class MailColumnProgress extends ColumnProgress {
    static props = {
        ...ColumnProgress.props,
        aggregateOn: { type: Object, optional: true },
    };
    static template = "mail.ColumnProgress";
}
