import { registry } from "@web/core/registry";
import { stepUtils } from "@web_tour/tour_utils";

registry.category("web_tour.tours").add("time_off_request_calendar_view", {
    url: "/odoo",
    steps: () => [
        stepUtils.showAppsMenuItem(),
        {
            content: "Open Time Off app",
            trigger: '.o_app[data-menu-xmlid="hr_holidays.menu_hr_holidays_root"]',
            run: "click",
        },
        {
            content: "Click on the first Thursday of the year",
            trigger: ".fc-daygrid-day.fc-day-thu",
            async run(helpers) {
                // The first `.fc-day-thu` cell is a disabled December cell in
                // any year whose January 1st falls on Friday through Sunday,
                // so aim at the first Thursday of the displayed year by date.
                const year = new Date().getFullYear();
                const first = new Date(Date.UTC(year, 0, 1));
                first.setUTCDate(first.getUTCDate() + ((4 - first.getUTCDay() + 7) % 7));
                const date = first.toISOString().slice(0, 10);
                await helpers.click(`.fc-daygrid-day[data-date="${date}"]`);
            },
        },
        {
            content: "Save the leave",
            trigger: '.btn:contains("Submit Request")',
            run: "click",
        },
    ],
});
