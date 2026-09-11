/** @odoo-module native */
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";
import { serializeDateTime, deserializeDateTime } from "@web/core/l10n/dates";
import { rpc } from "@web/core/network";
import { user } from "@web/core/user";
import { DateTime } from "luxon";
export class appointmentSlotSelect extends Interaction {
    static selector = ".o_appointment_info";
    dynamicContent = {
        "select[name='timezone']": {
            "t-on-change": this.debounced(this.onRefresh, 250),
        },
        "select[id='selectAppointmentResource']": {
            "t-on-change": this.debounced(this.onRefresh, 250),
        },
        "select[id='selectStaffUser']": {
            "t-on-change": this.debounced(this.onRefresh, 250),
        },
        "select[id='resourceCapacity']": {
            "t-on-change": this.debounced(this.onRefresh, 250),
        },
        ".o_js_calendar_navigate": {
            "t-on-click": this.onCalendarNavigate,
        },
        ".o_slot_button": {
            "t-on-click": this.onClickDaySlot,
        },
        ".o_slot_hours": {
            "t-on-click": this.onClickHoursSlot,
        },
        "button[name='submitSlotInfoSelected']": {
            "t-on-click": this.onClickConfirmSlot,
        },
        ".o_appointment_show_calendar": {
            "t-on-click": this.onClickShowCalendar,
        },
        "#next_available_slot": {
            "t-on-click": this.selectFirstAvailableMonth,
        },
        ".o_appointment_close_upcoming_appointment_alert .btn-close": {
            "t-on-click": this.onClickCloseUpcomingAppointmentAlert,
        },
    };

    setup() {
        // Block containing the availabilities
        this.slotsListEl = this.el.querySelector("#slotsList");
        // Resource or staff user selection, shown once an hour slot is picked
        this.resourceSelectionEl = this.el.querySelector("#resourceSelection");
        // First day containing an available slot
        this.firstEl = this.el.querySelector(".o_slot_button");
    }

    async start() {
        await this.initSlots();
        this.removeLoadingSpinner();
        this.firstEl?.click();
    }


    /**
     * Adapts the availability helpers to the calendar currently rendered.
     */
    async initSlots() {
        await this.updateSlotAvailability();
    }

    /**
     * Finds the first day with an available slot, replaces the currently shown month and
     * click on the first date where a slot is available.
     */
    selectFirstAvailableMonth() {
        const firstMonthEl = this.firstEl.closest(".o_appointment_month");
        const currentMonthEl = document.querySelector(
            ".o_appointment_month:not(.d-none)",
        );
        currentMonthEl.classList.add("d-none");
        currentMonthEl
            .querySelectorAll("table")
            .forEach((table) => table.classList.remove("d-none"));
        currentMonthEl.querySelector(".o_appointment_no_slot_month_helper").remove();
        firstMonthEl.classList.remove("d-none");
        this.slotsListEl.replaceChildren();
        this.firstEl.click();
    }

    /**
     * Hides the tables of a calendar month and appends the "no availability this
     * month" helper to it instead.
     *
     * @param {HTMLElement} monthEl the month div to which the helper is appended
     */
    renderNoAvailabilityForMonth(monthEl) {
        const firstAvailabilityDate = this.firstEl.getAttribute("id");
        const staffUserEl = this.el.querySelector(
            "#slots_form select[name='staff_user_id']",
        );
        const staffUserNameSelectedOption =
            staffUserEl?.options[staffUserEl.selectedIndex];
        const staffUserName = staffUserNameSelectedOption?.textContent;
        monthEl
            .querySelectorAll("table")
            .forEach((tableEl) => tableEl.classList.add("d-none"));

        this.renderAt(
            "Appointment.appointment_info_no_slot_month",
            {
                firstAvailabilityDate:
                    DateTime.fromISO(firstAvailabilityDate).toFormat(
                        "cccc dd MMMM yyyy",
                    ),
                staffUserName: staffUserName,
            },
            monthEl,
        );
    }

    _updateResourceCapacityOptions() {
        const capacitySelect = this.el.querySelector("select[name='resourceCapacity']");
        const resourceId = this.el.querySelector(
            "#slots_form select[name='resource_id']",
        )?.value;

        if (resourceId && capacitySelect?.value) {
            const max_resource_capacity = parseInt(
                this.el.querySelector("input[name='max_resource_capacity']")?.value ||
                    0,
            );
            const max_default_capacity = parseInt(
                this.el.querySelector("input[name='max_capacity']").value,
            );
            const previousCapacitySelected = parseInt(capacitySelect.value);
            const max_capacity = max_resource_capacity || max_default_capacity;
            capacitySelect.replaceChildren();
            this.renderAt(
                "calendar.booking.resources_capacity_options",
                {
                    asked_capacity:
                        previousCapacitySelected <= max_capacity
                            ? previousCapacitySelected
                            : false,
                    max_capacity: max_capacity,
                },
                capacitySelect,
            );
        }
    }

    /**
     * Adapts the calendar to the slots it holds.
     *
     * With no slot at all, empties the availabilities block, hides the timezone
     * selection and renders an explicative helper instead. When slots are only
     * missing for the capacity chosen, the details and the calendar stay visible
     * and only the capacity helper is rendered. Reveals the misconfiguration alert
     * (rendered by the template when the appointment type has no staff/resource or
     * no opening hours) and, unless dismissed, an alert for the visitor's next
     * upcoming appointment.
     */
    async updateSlotAvailability() {
        if (!this.firstEl) {
            // No slot available
            if (!this.el.querySelector("select[name='resourceCapacity']")) {
                this.el
                    .querySelectorAll("#slots_availabilities")
                    .forEach((slotEl) => slotEl.replaceChildren());
                this.el
                    .querySelector(".o_appointment_timezone_selection")
                    ?.classList.add("d-none");

                const staffUserEl = this.el.querySelector(
                    "#slots_form select[name='staff_user_id']",
                );
                const staffUserNameSelectedOption =
                    staffUserEl?.options[staffUserEl.selectedIndex];
                const staffUserName = staffUserNameSelectedOption?.textContent;
                const hideSelectDropdown = !!this.el.querySelector(
                    "input[name='hide_select_dropdown']",
                ).value;
                this.el
                    .querySelector(".o_appointment_no_slot_overall_helper")
                    .replaceChildren();
                this.renderAt(
                    "Appointment.appointment_info_no_slot",
                    {
                        active: this.el.querySelector("input[name='active']").value,
                        appointmentsCount: parseInt(
                            this.el.querySelector("#slotsList").dataset
                                .appointmentsCount,
                        ),
                        staffUserName: hideSelectDropdown ? staffUserName : false,
                    },
                    this.el.querySelector(".o_appointment_no_slot_overall_helper"),
                );
            } else {
                this.el.querySelector(".o_appointment_no_capacity")?.replaceChildren();
                this.renderAt(
                    "Appointment.appointment_info_no_capacity",
                    {},
                    this.el.querySelector(".o_appointment_no_capacity"),
                );
            }
        } else {
            this.el
                .querySelector(".o_appointment_timezone_selection")
                ?.classList.remove("d-none");
            this.el.querySelector(".o_appointment_no_capacity")?.replaceChildren();
        }
        this.el
            .querySelector(".o_appointment_missing_configuration")
            ?.classList.remove("d-none");
        // Check upcoming appointments
        const allAppointmentsToken =
            JSON.parse(
                localStorage.getItem("appointment.upcoming_events_access_token"),
            ) || [];
        const ignoreUpcomingEventUntil = localStorage.getItem(
            "appointment.upcoming_events_ignore_until",
        );
        if (
            !this.el.querySelector(".o_appointment_cancelled") &&
            !this.el.querySelector(".o_appointment_forced_staff_user_assigned") &&
            (!ignoreUpcomingEventUntil ||
                deserializeDateTime(ignoreUpcomingEventUntil) < DateTime.utc()) &&
            (allAppointmentsToken.length !== 0 || user.userId !== false)
        ) {
            const upcomingAppointmentData = await this.waitFor(
                rpc("/appointment/get_upcoming_appointments", {
                    calendar_event_access_tokens: allAppointmentsToken,
                }),
            );
            this.bindDeferred(() => {
                if (upcomingAppointmentData) {
                    if (
                        !localStorage.getItem(
                            "appointment.hide_upcoming_appointment_alert",
                        )
                    ) {
                        const timezone = this.el.querySelector(
                            ".o_appointment_info_main",
                        ).dataset.timezone;
                        const upcomingFormattedStart = deserializeDateTime(
                            upcomingAppointmentData.next_upcoming_appointment.start,
                        )
                            .setZone(timezone)
                            .toLocaleString(DateTime.DATETIME_MED_WITH_WEEKDAY);

                        this.el
                            .querySelector(".o_appointment_upcoming_appointment_alert")
                            .replaceChildren();
                        this.renderAt(
                            "Appointment.appointment_info_upcoming_appointment",
                            {
                                appointmentTypeName:
                                    upcomingAppointmentData.next_upcoming_appointment
                                        .appointment_type_id[1],
                                appointmentStart: upcomingFormattedStart,
                                appointmentToken:
                                    upcomingAppointmentData.next_upcoming_appointment
                                        .access_token,
                                partnerId:
                                    upcomingAppointmentData.next_upcoming_appointment
                                        .appointment_booker_id[0],
                            },
                            this.el.querySelector(
                                ".o_appointment_upcoming_appointment_alert",
                            ),
                        );

                        if (user.userId === false) {
                            localStorage.setItem(
                                "appointment.upcoming_events_access_token",
                                JSON.stringify(
                                    upcomingAppointmentData.valid_access_tokens,
                                ),
                            );
                        }
                    } else {
                        localStorage.removeItem(
                            "appointment.upcoming_events_access_token",
                        );
                    }
                }
            })();
        }
    }

    /**
     * Navigate between the months available in the calendar displayed
     */
    onCalendarNavigate(ev) {
        const parentEl = this.el.querySelector(".o_appointment_month:not(.d-none)");
        let monthID = parseInt(parentEl.getAttribute("id").split("-")[1]);
        monthID += ev.currentTarget.getAttribute("id") === "nextCal" ? 1 : -1;
        parentEl
            .querySelectorAll("table")
            .forEach((table) => table.classList.remove("d-none"));
        parentEl
            .querySelectorAll(".o_appointment_no_slot_month_helper")
            .forEach((element) => element.remove());
        parentEl.classList.add("d-none");
        const monthEl = this.el.querySelector(`div#month-${monthID}`);
        monthEl.classList.remove("d-none");
        this.el.querySelector(".active")?.classList.remove("active");
        this.slotsListEl.replaceChildren();
        this.resourceSelectionEl?.replaceChildren();

        if (this.firstEl) {
            // If there is at least one slot available, check if it is in the current month.
            if (!monthEl.querySelector(".o_day")) {
                this.renderNoAvailabilityForMonth(monthEl);
            }
        }
    }

    /**
     * Display the list of slots available for the date selected
     */
    onClickDaySlot(ev) {
        this.el
            .querySelectorAll(".o_slot_selected")
            .forEach((slot) => slot.classList.remove("o_slot_selected", "active"));
        ev.currentTarget.classList.add("o_slot_selected", "active");

        // Do not display slots until user has actively selected the capacity
        const resourceCapacityEl = this.el.querySelector(
            "select[name='resourceCapacity']",
        );
        const resourceCapacitySelectedOption =
            resourceCapacityEl?.options[resourceCapacityEl.selectedIndex];
        if (
            resourceCapacitySelectedOption &&
            resourceCapacitySelectedOption.dataset.placeholderOption
        ) {
            return;
        }
        const slotDate = ev.currentTarget.dataset.slotDate;
        const slots = JSON.parse(ev.currentTarget.dataset.availableSlots);
        const scheduleBasedOn = this.el.querySelector(
            "input[name='schedule_based_on']",
        ).value;
        const selectAppointmentResourceEl = this.el.querySelector(
            "select[id='selectAppointmentResource']",
        );
        const resourceId =
            (selectAppointmentResourceEl && selectAppointmentResourceEl.value) ||
            this.el.querySelector("input[name='resource_selected_id']").value;
        const resourceCapacity = this.el.querySelector(
            "select[name='resourceCapacity']",
        )?.value;
        let commonUrlParams = new URLSearchParams(window.location.search);
        // The url may still carry the staff user, resource, duration and date_time of a
        // previous booking attempt (e.g. slot already taken, visitor sent back to the
        // calendar). Drop them so they do not interfere with the values bound to the
        // slot clicked now.
        commonUrlParams.delete("staff_user_id");
        commonUrlParams.delete("resource_selected_id");
        commonUrlParams.delete("duration");
        commonUrlParams.delete("date_time");
        if (resourceCapacity) {
            commonUrlParams.set("asked_capacity", encodeURIComponent(resourceCapacity));
        }
        if (resourceId) {
            commonUrlParams.set("resource_selected_id", encodeURIComponent(resourceId));
        }

        this.slotsListEl.replaceChildren();
        this.renderAt(
            "calendar.booking.slots_list",
            {
                commonUrlParams: commonUrlParams,
                scheduleBasedOn: scheduleBasedOn,
                slotDate: DateTime.fromISO(slotDate).toFormat("cccc dd MMMM yyyy"),
                slots: slots,
                getAvailableResources: (slot) => {
                    return scheduleBasedOn === "resources"
                        ? JSON.stringify(slot["available_resources"])
                        : false;
                },
                getAvailableUsers: (slot) => {
                    return scheduleBasedOn === "users"
                        ? JSON.stringify(slot["available_staff_users"])
                        : false;
                },
            },
            this.slotsListEl,
        );
        this.resourceSelectionEl?.classList.add("d-none");
    }

    onClickHoursSlot(ev) {
        this.el
            .querySelector(".o_slot_hours.o_slot_hours_selected")
            ?.classList.remove("o_slot_hours_selected", "active");
        ev.currentTarget.classList.add("o_slot_hours_selected", "active");

        // Outside 'manual + date first' the slot url is opened directly; in that flow we
        // first let the user select a resource before confirming the slot.
        const isAutoAssign = this.el.querySelector(
            "input[name='is_auto_assign']",
        ).value;
        const isDateFirst = this.el.querySelector("input[name='is_date_first']").value;
        const scheduleBasedOn = this.el.querySelector(
            "input[name='schedule_based_on']",
        ).value;
        if (isAutoAssign || !isDateFirst) {
            const appointmentTypeID = this.el.querySelector(
                "input[name='appointment_type_id']",
            ).value;
            const urlParameters = decodeURIComponent(
                this.el.querySelector(".o_slot_hours_selected").dataset.urlParameters,
            );
            const url = new URL(
                `/appointment/${encodeURIComponent(appointmentTypeID)}/info?${urlParameters}`,
                location.origin,
            );
            document.location = encodeURI(url.href);
            return;
        }

        const availableResources = ev.currentTarget.dataset.availableResources
            ? JSON.parse(ev.currentTarget.dataset.availableResources)
            : undefined;
        const availableStaffUsers = ev.currentTarget.dataset.availableStaffUsers
            ? JSON.parse(ev.currentTarget.dataset.availableStaffUsers)
            : undefined;
        const previousResourceIdSelected = this.el.querySelector(
            "select[name='resource_id']",
        )?.value;
        this.resourceSelectionEl.replaceChildren();
        this.renderAt(
            "calendar.booking.resources_list",
            {
                availableResources,
                availableStaffUsers,
                scheduleBasedOn,
            },
            this.resourceSelectionEl,
        );
        const availableEntity =
            scheduleBasedOn === "resources" ? availableResources : availableStaffUsers;
        const resourceIdEl = this.el.querySelector("select[name='resource_id']");
        if (availableEntity.length === 1) {
            resourceIdEl.setAttribute("disabled", true);
        }
        if (
            previousResourceIdSelected &&
            this.el.querySelector(
                `select[name='resource_id'] > option[value='${previousResourceIdSelected}']`,
            )
        ) {
            resourceIdEl.value = previousResourceIdSelected;
        }
        this.resourceSelectionEl.classList.remove("d-none");
    }

    onClickConfirmSlot() {
        const appointmentTypeID = this.el.querySelector(
            "input[name='appointment_type_id']",
        ).value;
        const resourceId = parseInt(
            this.el.querySelector("select[name='resource_id']").value,
        );
        const scheduleBasedOn = this.el.querySelector(
            "input[name='schedule_based_on']",
        ).value;
        const urlParameters = decodeURIComponent(
            this.el.querySelector(".o_slot_hours_selected").dataset.urlParameters,
        );
        const url = new URL(
            `/appointment/${encodeURIComponent(appointmentTypeID)}/info?${urlParameters}`,
            location.origin,
        );
        const isAutoAssign = this.el.querySelector(
            "input[name='is_auto_assign']",
        ).value;
        const isDateFirst = this.el.querySelector("input[name='is_date_first']").value;
        if (scheduleBasedOn === "resources") {
            const resourceCapacity =
                parseInt(
                    this.el.querySelector("select[name='resourceCapacity']")?.value,
                ) || 1;
            const resourceSelected =
                this.el.querySelector(".o_resources_list").selectedOptions[0];
            let resourceIds = JSON.parse(
                url.searchParams.get("available_resource_ids"),
            );
            if (
                isDateFirst &&
                !isAutoAssign &&
                parseInt(resourceSelected.dataset.resourceCapacity) >= resourceCapacity
            ) {
                resourceIds = [resourceId];
            }
            url.searchParams.set(
                "resource_selected_id",
                encodeURIComponent(resourceId),
            );
            url.searchParams.set("available_resource_ids", JSON.stringify(resourceIds));
            url.searchParams.set(
                "asked_capacity",
                encodeURIComponent(resourceCapacity),
            );
        } else {
            url.searchParams.set("staff_user_id", encodeURIComponent(resourceId));
        }
        document.location = encodeURI(url.href);
    }

    onClickShowCalendar() {
        this.el.querySelector(".o_appointment_no_slot_overall_helper").textContent = "";
        this.el.querySelector("div.o_appointment_calendar").classList.remove("d-none");
        this.el
            .querySelector("div.o_appointment_calendar_form")
            .classList.remove("d-none");
        localStorage.setItem(
            "appointment.upcoming_events_ignore_until",
            serializeDateTime(DateTime.utc().plus({ days: 1 })),
        );
    }

    /**
     * Refresh the slots info when the user modifies the timezone, the staff user,
     * the resource or the capacity.
     */
    async onRefresh() {
        if (this.el.querySelector("#slots_availabilities")) {
            const daySlotSelected =
                this.el.querySelector(".o_slot_selected") &&
                this.el.querySelector(".o_slot_selected").dataset.slotDate;
            const appointmentTypeID = this.el.querySelector(
                "input[name='appointment_type_id']",
            ).value;
            const filterAppointmentTypeIds = this.el.querySelector(
                "input[name='filter_appointment_type_ids']",
            ).value;
            const filterUserIds = this.el.querySelector(
                "input[name='filter_staff_user_ids']",
            ).value;
            const inviteToken = this.el.querySelector(
                "input[name='invite_token']",
            ).value;
            const previousMonthName = this.el.querySelector(
                ".o_appointment_month:not(.d-none) .o_appointment_month_name",
            )?.textContent;
            const staffUserID = this.el.querySelector(
                "#slots_form select[name='staff_user_id']",
            )?.value;
            const resourceID =
                this.el.querySelector("select[id='selectAppointmentResource']")
                    ?.value ||
                this.el.querySelector("input[name='resource_selected_id']")?.value;
            const filterResourceIds = this.el.querySelector(
                "input[name='filter_resource_ids']",
            ).value;
            const timezone = this.el.querySelector("select[name='timezone']")?.value;
            const resourceCapacity =
                (this.el.querySelector("select[name='resourceCapacity']") &&
                    parseInt(
                        this.el.querySelector("select[name='resourceCapacity']").value,
                    )) ||
                1;
            this.el
                .querySelector(".o_appointment_no_slot_overall_helper")
                .replaceChildren();
            this.slotsListEl.replaceChildren();
            this.el
                .querySelectorAll("#calendar, .o_appointment_timezone_selection")
                .forEach((el) => {
                    el.classList.add("o_appointment_disable_calendar");
                });
            this.resourceSelectionEl?.replaceChildren();
            const resourceCapacityEl = this.el.querySelector(
                "select[name='resourceCapacity']",
            );
            const resourceCapacitySelectedOption =
                resourceCapacityEl?.options[resourceCapacityEl.selectedIndex];
            if (
                daySlotSelected &&
                !(
                    resourceCapacitySelectedOption &&
                    resourceCapacitySelectedOption.dataset.placeholderOption
                )
            ) {
                this.el
                    .querySelector(".o_appointment_slot_list_loading")
                    .classList.remove("d-none");
            }
            let updatedAppointmentCalendarHtml;
            try {
                updatedAppointmentCalendarHtml = await rpc(
                    `/appointment/${appointmentTypeID}/update_available_slots`,
                    {
                        asked_capacity: resourceCapacity,
                        invite_token: inviteToken,
                        filter_appointment_type_ids: filterAppointmentTypeIds,
                        filter_staff_user_ids: filterUserIds,
                        filter_resource_ids: filterResourceIds,
                        month_before_update: previousMonthName,
                        resource_selected_id: resourceID,
                        staff_user_id: staffUserID,
                        timezone: timezone,
                    },
                );
            } catch (error) {
                // Do not leave the calendar disabled/spinning forever on a server error.
                this.removeLoadingSpinner();
                throw error;
            }
            if (updatedAppointmentCalendarHtml) {
                this.el.querySelector("#slots_availabilities").outerHTML =
                    updatedAppointmentCalendarHtml;
                this.initSlots();
                this._updateResourceCapacityOptions();
                // If possible, we keep the current month, and display the helper if it has no availability.
                const displayedMonthEl = this.el.querySelector(
                    ".o_appointment_month:not(.d-none)",
                );
                if (!!this.firstEl && !displayedMonthEl.querySelector(".o_day")) {
                    this.renderNoAvailabilityForMonth(displayedMonthEl);
                }
                this.removeLoadingSpinner();
                // Select previous selected date (in displayed month) if possible.
                const selectedDayEl = displayedMonthEl?.querySelector(
                    `div[data-slot-date="${daySlotSelected}"]`,
                );
                selectedDayEl && this.onClickDaySlot({ currentTarget: selectedDayEl });
            }
        }
    }

    /**
     * Remove the loading spinners and re-enable the calendar once slots are rendered.
     */
    removeLoadingSpinner() {
        this.el.querySelector(".o_appointment_slots_loading")?.remove();
        this.el
            .querySelector(".o_appointment_slot_list_loading")
            ?.classList.add("d-none");
        this.el.querySelector("#slots_availabilities")?.classList.remove("d-none");
        this.el
            .querySelectorAll("#calendar, .o_appointment_timezone_selection")
            .forEach((el) => {
                el.classList.remove("o_appointment_disable_calendar");
            });
    }

    onClickCloseUpcomingAppointmentAlert() {
        localStorage.setItem("appointment.hide_upcoming_appointment_alert", true);
        this.el
            .querySelector(".o_appointment_close_upcoming_appointment_alert")
            ?.remove();
    }
}

registry
    .category("public.interactions")
    .add("appointment.appointment_select_appointment_slot", appointmentSlotSelect);
