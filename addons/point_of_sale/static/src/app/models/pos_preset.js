/** @odoo-module native */
import { luxon } from "@web/core/l10n/luxon";
import { registry } from "@web/core/registry";

import { Base } from "./related_models/index.js";
const { DateTime } = luxon;

export class PosPreset extends Base {
    static pythonModel = "pos.preset";
    static excludedLazyGetters = [
        ...Base.excludedLazyGetters,
        "nextSlot",
        "currentSlot",
        "availabilities",
    ];

    initState() {
        super.initState();
        this.uiState = {
            availabilities: {},
        };

        this.computeAvailabilities();
    }

    get needsSlot() {
        return this.use_timing;
    }

    get needsName() {
        return this.identification === "name";
    }

    get needsPartner() {
        return this.identification === "address";
    }

    get orders() {
        return this.models["pos.order"].filter((o) => o.preset_id?.id === this.id);
    }

    get nextSlot() {
        const dateNow = DateTime.now();
        const sqlDate = dateNow.toFormat("yyyy-MM-dd");
        return Object.values(this.availabilities[sqlDate] || {}).find(
            (s) => !s.isFull && s.datetime >= dateNow,
        );
    }

    get availabilities() {
        const now = DateTime.now();
        if (this.uiState.generatedFor !== `${now.toISODate()}/${now.zoneName}`) {
            this.computeAvailabilities(this.uiState.serverUsage, now);
        }
        return this.uiState.availabilities;
    }

    get slotsUsage() {
        return (
            this.orders.reduce((acc, order) => {
                if (!order.preset_time || order.state === "cancel") {
                    return acc;
                }
                const key = order.preset_time.toFormat("yyyy-MM-dd HH:mm:ss");
                if (!acc[key]) {
                    acc[key] = [];
                }
                acc[key].push(order.id);
                return acc;
            }, {}) || {}
        );
    }

    computeAvailabilities(usages = {}, now = DateTime.now()) {
        this.uiState.serverUsage = usages;
        this.generateSlots(now);

        const allSlots = Object.values(this.uiState.availabilities).reduce(
            (acc, curr) => Object.assign(acc, curr),
            {},
        );

        for (const [datetime, slot] of Object.entries(allSlots)) {
            const usage = usages[datetime];
            slot.order_ids = new Set([...slot.order_ids, ...(usage || [])]);
            slot.isFull = slot.order_ids.size >= this.slots_per_interval;
        }

        return this.uiState.availabilities;
    }

    get currentSlot() {
        const now = DateTime.now();
        const interval = this.interval_time;
        const todayAvailabilities =
            this.availabilities[now.toFormat("yyyy-MM-dd")] || {};
        for (const slot of Object.values(todayAvailabilities)) {
            if (
                slot.datetime <= now &&
                slot.datetime.plus({ minutes: interval }) > now
            ) {
                return slot;
            }
        }
        return false;
    }

    generateSlots(now = DateTime.now()) {
        const usage = this.slotsUsage;
        const interval = this.interval_time;
        const slots = {};

        for (const i of [...Array(7).keys()]) {
            const dateNow = now.plus({ days: i });
            const getDateTime = (hour) =>
                dateNow
                    .startOf("day")
                    .plus({ days: Math.floor(hour / 24) })
                    .set({
                        hour: Math.floor(hour) % 24,
                        minute: Math.round((hour % 1) * 60),
                    });
            const dayOfWeek = (dateNow.weekday - 1).toString();
            const date = dateNow.toFormat("yyyy-MM-dd");
            const attToday = this.attendance_ids.filter(
                (a) => a.dayofweek === dayOfWeek,
            );
            slots[date] = {};

            for (const attendance of attToday) {
                const dateOpening = getDateTime(attendance.hour_from);
                const dateClosing = getDateTime(attendance.hour_to);

                let start = dateOpening;
                while (start >= dateOpening && start <= dateClosing && interval > 0) {
                    const sqlDatetime = start.toFormat("yyyy-MM-dd HH:mm:ss");

                    if (slots[date][sqlDatetime]) {
                        for (const id of usage[sqlDatetime] || []) {
                            slots[date][sqlDatetime].order_ids.add(id);
                        }
                    } else {
                        slots[date][sqlDatetime] = {
                            periode: attendance.day_period,
                            datetime: start,
                            order_ids: new Set(usage[sqlDatetime] || []),
                        };
                    }
                    start = start.plus({ minutes: interval });
                }
            }
        }

        this.uiState.availabilities = slots;
        this.uiState.generatedFor = `${now.toISODate()}/${now.zoneName}`;
    }
}

registry.category("pos_available_models").add(PosPreset.pythonModel, PosPreset);
