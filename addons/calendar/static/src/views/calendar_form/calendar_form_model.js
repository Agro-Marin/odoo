/** @odoo-module native */
import { RelationalModel, RelationalRecord } from "@web/model/relational_model";

class CalendarFormRecord extends RelationalRecord {
    async setLocation() {
        const videoLocation = await this.model.orm.call(
            "calendar.event",
            "get_discuss_videocall_location",
        );
        this.update({
            access_token: videoLocation.split("/").pop(),
            videocall_location: videoLocation,
            videocall_source: "discuss",
        });
    }

    async clearLocation() {
        this.update({
            videocall_location: false,
            videocall_source: "custom",
        });
    }
}

export class CalendarFormModel extends RelationalModel {
    static Record = CalendarFormRecord;
}
