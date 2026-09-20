/** @odoo-module native */
import { useComponent, useEffect, useEnv, useState } from "@odoo/owl";
import { localization } from "@web/core/l10n/localization";

/**
 * Common code between common and year renderer for our calendar.
 */
export function useAppointmentRendererHook(getFcElements) {
    const component = useComponent();
    const env = useEnv();
    useState(env.calendarState);

    /**
     * Display an overlay when using the slots selection mode that
     * encompasses the past time.
     */
    useEffect(
        (fcEls, calendarMode) => {
            if (calendarMode === "slots-creation") {
                for (const fcEl of fcEls) {
                    const daysToDisable = fcEl.querySelectorAll(
                        ".fc-day-past:not(.fc-col-header-cell), .fc-day-today:not(.fc-col-header-cell)",
                    );
                    fcEl.classList.add("o_calendar_slots_in_creation");
                    for (const el of daysToDisable) {
                        el.classList.add("o_calendar_slot_selection");
                    }
                    const todayColumn = fcEl.querySelectorAll(
                        ".fc-day-today:not(.fc-col-header-cell)",
                    )[1];
                    const bgColumn = todayColumn?.querySelector(".fc-timegrid-col-bg");
                    const nowIndicator = todayColumn?.querySelector(
                        ".fc-timegrid-now-indicator-line",
                    );
                    // Create a block for today to have the overlay size based on the current hour
                    if (
                        bgColumn &&
                        nowIndicator &&
                        ["timeGridWeek", "timeGridDay"].includes(
                            component.fc.api.view.type,
                        )
                    ) {
                        const height = nowIndicator.style.top.slice(0, -2);
                        const childEl = document.createElement("div");
                        childEl.classList.add(
                            "o_calendar_slot_selection_now",
                            "position-absolute",
                            "start-0",
                            "end-0",
                        );
                        childEl.style.height = `${height}px`;
                        bgColumn.appendChild(childEl);
                    }
                }
                return () => {
                    for (const fcEl of fcEls) {
                        const daysToDisable = fcEl.querySelectorAll(
                            ".fc-day-past:not(.fc-col-header-cell), .fc-day-today:not(.fc-col-header-cell)",
                        );
                        fcEl.classList.remove("o_calendar_slots_in_creation");
                        for (const el of daysToDisable) {
                            el.classList.remove("o_calendar_slot_selection");
                        }
                        const todayColumn = fcEl.querySelectorAll(
                            ".fc-day-today:not(.fc-col-header-cell)",
                        )[1];
                        if (todayColumn) {
                            const childEl = todayColumn.querySelector(
                                ".o_calendar_slot_selection_now",
                            );
                            childEl && childEl.remove();
                        }
                    }
                };
            }
        },
        () => [getFcElements(), env.calendarState.mode],
    );
    return {
        isSlotCreationMode() {
            return env.calendarState.mode === "slots-creation";
        },

        getEventTimeFormat() {
            const format12Hour = {
                hour: "numeric",
                minute: "2-digit",
                omitZeroMinute: true,
                meridiem: "short",
            };
            const format24Hour = {
                hour: "numeric",
                minute: "2-digit",
                hour12: false,
            };
            return localization.timeFormat.search("HH") === 0
                ? format24Hour
                : format12Hour;
        },
    };
}

/**
 * The slots are an event source of their own: the calendar hook refetches only
 * when a source changes identity, and the model replaces `data.slots` on every
 * slot change. Shared by the common and year calendar renderers.
 *
 * @param {Component} component the patched renderer instance
 * @param {unknown[]} superSources the result of the un-patched eventSources
 */
export function eventSourcesWithSlots(component, superSources) {
    return [...superSources, component.props.model.data.slots];
}

/**
 * Converts an appointment.slot record into an editable fullcalendar event.
 * Shared by the common and year calendar renderers.
 *
 * @param {Component} component the patched renderer instance
 * @param {Object} record the slot record to convert
 */
export function convertSlotToEvent(component, record) {
    const result = {
        ...component.convertRecordToEvent(record),
        id: component.maxResId + record.id, // Arbitrary id to avoid duplicated ids.
        slotId: record.id,
    };
    result.editable = true; // Keep slots editable
    return result;
}

/**
 * Appends the slot events to the records-derived fullcalendar events, and
 * (re)computes maxResId used to build their ids. Shared by the common and
 * year calendar renderers, each of which must still call its own
 * `super.mapRecordsToEvents(...)` (the `super` binding cannot cross files).
 *
 * @param {Component} component the patched renderer instance
 * @param {Array} superEvents the result of the un-patched mapRecordsToEvents
 */
export function mapRecordsAndSlotsToEvents(component, superEvents) {
    component.maxResId = Math.max(
        0,
        ...Object.keys(component.props.model.data.records).map((id) =>
            Number.parseInt(id),
        ),
    );
    return [
        ...superEvents,
        ...Object.values(component.props.model.data.slots).map((r) =>
            convertSlotToEvent(component, r),
        ),
    ];
}

/**
 * Carries the slot id over to the record built from a fullcalendar event.
 * Shared by the common and year calendar renderers, each of which must
 * still call its own `super.fcEventToRecord(...)`.
 *
 * @param {Object} event the fullcalendar event
 * @param {Object} superRecord the result of the un-patched fcEventToRecord
 */
export function fcEventToRecordWithSlot(event, superRecord) {
    return {
        ...superRecord,
        slotId: event.extendedProps.slotId,
    };
}
