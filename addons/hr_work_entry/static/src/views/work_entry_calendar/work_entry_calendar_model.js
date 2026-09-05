/** @odoo-module native */
import { serializeDate } from "@web/core/l10n/dates";
import { useService } from "@web/core/utils/hooks";
import { CalendarModel } from "@web/views/calendar";
import { fetchUserFavoritesWorkEntries } from "@hr_work_entry/views/work_entry_favorites";

export class WorkEntryCalendarModel extends CalendarModel {
    setup() {
        super.setup(...arguments);
        this.orm = useService("orm");
    }

    /** @override */
    async updateData(data) {
        const { start, end } = this.computeRange();
        await this.orm.call("hr.employee", "generate_work_entries", [
            [this.meta.context.default_employee_id],
            serializeDate(start),
            serializeDate(end),
        ]);
        await Promise.all([
            super.updateData(data),
            fetchUserFavoritesWorkEntries(this.orm).then((favorites) => {
                this.userFavoritesWorkEntries = favorites;
            }),
        ]);
    }

    async multiReplaceRecords(values, dates, records) {
        if (!dates.length) {
            return;
        }
        const new_records = [];
        const quickreplace = values.duration < 0;
        const newly_generated_entries = [];
        for (const date of dates) {
            const rawRecord = this.buildRawRecord({ start: date });
            if (quickreplace) {
                const selected_date_records = records.filter(
                    (r) => r.date === rawRecord.date,
                );
                const existing_duration = selected_date_records.reduce(
                    (acc, r) => acc + r.duration,
                    0,
                );
                if (existing_duration > 0) values.duration = existing_duration;
                else {
                    const generated_work_entry = await this.orm.call(
                        "hr.employee",
                        "generate_work_entries",
                        [values.employee_id, date, date, true],
                    );
                    if (generated_work_entry.length > 0)
                        newly_generated_entries.push(generated_work_entry[0]);
                    continue;
                }
            }
            new_records.push({
                ...rawRecord,
                ...values,
            });
        }
        if (newly_generated_entries.length) {
            await this.orm.write("hr.work.entry", newly_generated_entries, {
                work_entry_type_id: values.work_entry_type_id,
            });
        }
        if (records.length) {
            await this.orm.unlink(
                this.meta.resModel,
                records.map((r) => r.id),
            );
        }
        if (new_records.length) {
            await this.orm.create(this.meta.resModel, new_records, {
                context: this.meta.context,
            });
        }
        return this.load();
    }

    async resetWorkEntries(dates) {
        const cellsFormattedData = dates.map((date) => ({
            date,
            employee_id: this.meta.context.default_employee_id,
        }));
        await this.orm.call(
            "hr.work.entry.regeneration.wizard",
            "regenerate_work_entries",
            [[], cellsFormattedData],
        );
        return this.load();
    }
}
