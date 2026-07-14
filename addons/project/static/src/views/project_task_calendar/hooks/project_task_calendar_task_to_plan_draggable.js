/** @odoo-module native */
import { onWillUnmount, reactive, useEffect, useExternalListener } from "@odoo/owl";
import { makeDraggableHook } from "@web/core/utils/dnd/draggable_hook_builder";
import { pick } from "@web/core/utils/collections/objects";
import { useThrottleForAnimation } from "@web/core/utils/timing";

const hookParams = {
    name: "useCalendarTaskToPlanDraggable",
    onDragStart(params) {
        const { ctx, addClass, addListener, addStyle, callHandler, getRect, removeClass, removeStyle } = params;

        const onElementPointerEnter = (ev) => {
            const element = ev.currentTarget;
            current.calendarCell = element;
            current.timeSlotElement = null;
            callHandler("onElementEnter", { element });
        };

        const onElementPointerLeave = (ev) => {
            const element = ev.currentTarget;
            current.calendarCell = null;
            callHandler("onElementLeave", { element });
        };

        const onTimeSlotElementPointerEnter = (ev) => {
            const element = ev.currentTarget;
            current.timeSlotElement = element;
            callHandler("onElementEnter", { element });
        }

        const onTimeSlotElementPointerLeave = (ev) => {
            const element = ev.currentTarget;
            current.timeSlotElement = null;
            callHandler("onElementLeave", { element })
        }

        const { ref, current } = ctx;
        // The drag builder just set `pe-none` on <body> (before calling this
        // handler), which pointer-events-disables every descendant: without
        // re-enabling our own subtree, the pointerenter/pointermove listeners
        // below can never fire and `elementsFromPoint` skips the calendar, so
        // no cell could ever highlight or receive the drop (the dragged ghost
        // itself stays inert through `.o_dragged { pointer-events: none }`).
        // Same compensation as web's square_selection_hook.
        addClass(ref.el, "pe-auto");
        const containerSelector = ".o_calendar_renderer .o_calendar_widget";
        let selector = `${containerSelector} .fc-timegrid-slot.fc-timegrid-slot-lane`;
        const slotElements = ref.el.querySelectorAll(selector);
        if (slotElements.length) {
            const eventContainer = ref.el.querySelector(".o_calendar_renderer .o_task_event_to_plan_container");

            const onTimeGridPointerMove = (ev) => {
                // In the time grid, `.fc-day` columns sit under the slot lanes
                // and never receive pointerenter, so hit-test them explicitly.
                const nodes = document.elementsFromPoint(ev.clientX, ev.clientY);
                current.calendarCell =
                    nodes.find((node) => node.classList.contains("fc-day")) || null;
                if (eventContainer && current.calendarCell && current.timeSlotElement) {
                    const { bottom, height } = getRect(current.timeSlotElement, { adjust: true });
                    const { left, width } = getRect(current.calendarCell, { adjust: true });
                    addStyle(eventContainer, {
                        bottom: `${document.documentElement.clientHeight - bottom - height}px`,
                        width:`${width}px`,
                        left: `${left}px`,
                        height: `${height * 2}px`,
                    });
                    removeClass(eventContainer, "d-none");
                } else if (eventContainer) {
                    removeStyle(eventContainer, "bottom", "width", "left", "height");
                    addClass(eventContainer, "d-none");
                }
            }

            const onTimeGridPointerCancel = () => {
                current.calendarCell = null;
                current.timeSlotElement = null;
                if (eventContainer) {
                    removeStyle(eventContainer, "bottom", "width", "left", "height");
                    addClass(eventContainer, "d-none");
                }
            }

            for (const timeSlotCalendarCell of slotElements) {
                addListener(timeSlotCalendarCell, "pointerenter", onTimeSlotElementPointerEnter);
                addListener(timeSlotCalendarCell, "pointerleave", onTimeSlotElementPointerLeave);
            }
            const timeSlotContainerEl = ref.el.querySelector(`${containerSelector} .fc-timegrid-body`);
            addListener(timeSlotContainerEl, "pointermove", onTimeGridPointerMove);
            addListener(timeSlotContainerEl, "pointercancel", onTimeGridPointerCancel);
        }
        selector = `${containerSelector} .fc-day`;
        for (const calendarCell of ref.el.querySelectorAll(selector)) {
            addListener(calendarCell, "pointerenter", onElementPointerEnter);
            addListener(calendarCell, "pointerleave", onElementPointerLeave);
        }
        return pick(current, "element");
    },
    onDragEnd({ ctx }) {
        return pick(ctx.current, "element", "calendarCell");
    },
    onDrop({ ctx}) {
        const { element, calendarCell, timeSlotElement } = ctx.current;
        if (element && calendarCell) {
            return {
                element,
                calendarCell,
                timeSlotElement,
            }
        }
    },
};
export function useCalendarTaskToPlanDraggable(params) {
    const setupHooks = {
        addListener: useExternalListener,
        setup: useEffect,
        teardown: onWillUnmount,
        throttle: useThrottleForAnimation,
        wrapState: reactive,
    };
    return makeDraggableHook({ ...hookParams, setupHooks })(params);
}
