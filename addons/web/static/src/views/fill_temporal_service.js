// @ts-check
/** @odoo-module native */
import { serializeDate, serializeDateTime } from "@web/core/l10n/dates";
import { luxon } from "@web/core/l10n/luxon";
import { registry } from "@web/core/registry";

/**
 * @typedef {import("@web/core/l10n/luxon").DateTime} DateTime
 * @typedef {{ name: string, type: "date" | "datetime" }} TemporalField
 * @typedef {{
 *     startOf: (dt: DateTime) => DateTime,
 *     cycle: number,
 *     cyclePos: (dt: DateTime) => number,
 * }} GranularityConfig
 * @typedef {{
 *     min_groups: number,
 *     fill_from?: string | false,
 *     fill_to?: string | false,
 * }} FillTemporalContext
 */

/**
 * @type {Record<string, GranularityConfig>}
 */
export const GRANULARITY_TABLE = {
    hour: {
        startOf: (x) => x.startOf("hour"),
        cycle: 24,
        cyclePos: (x) => x.hour + 1,
    },
    day: {
        startOf: (x) => x.startOf("day"),
        cycle: 7,
        cyclePos: (x) => x.weekday,
    },
    week: {
        startOf: (x) => x.startOf("week"),
        cycle: 1,
        cyclePos: () => 1,
    },
    month: {
        startOf: (x) => x.startOf("month"),
        cycle: 12,
        cyclePos: (x) => x.month,
    },
    quarter: {
        startOf: (x) => x.startOf("quarter"),
        cycle: 4,
        cyclePos: (x) => x.quarter,
    },
    year: {
        startOf: (x) => x.startOf("year"),
        cycle: 1,
        cyclePos: () => 1,
    },
};

const DEFAULT_MIN_GROUPS = 4;

export class FillTemporalPeriod {
    /**
     * @type {DateTime}
     */
    start;

    /** @type {DateTime} */
    end;

    /** @type {boolean} */
    computedEnd;

    /** @type {number} */
    minGroups;

    /**
     * @param {string} modelName directly taken from model.loadParams.modelName.
     *                           this is the `res_model` from the action (i.e. `crm.lead`)
     * @param {TemporalField} field a dictionary with keys "name" and "type".
     *                        name: Name of the field on which the fill_temporal should apply
     *                              (i.e. 'date_deadline')
     *                        type: 'date' or 'datetime'
     * @param {string} granularity can either be : hour, day, week, month, quarter, year
     * @param {number} minGroups minimum amount of groups to display, regardless of other
     *                            constraints
     */
    constructor(modelName, field, granularity, minGroups) {
        this.modelName = modelName;
        this.field = field;
        this.granularity = granularity || "month";
        this.setMinGroups(minGroups);

        this._computeStart();
        this._computeEnd();
    }
    /**
     * @private
     */
    _computeStart() {
        this.start = GRANULARITY_TABLE[this.granularity].startOf(luxon.DateTime.now());
    }
    /**
     * @private
     */
    _computeEnd() {
        const cycle = GRANULARITY_TABLE[this.granularity].cycle;
        const cyclePos = GRANULARITY_TABLE[this.granularity].cyclePos(this.start);
        const fillTemporalPeriod =
            ((2 * cycle - ((this.minGroups - 1) % cycle) - cyclePos) % cycle) +
            this.minGroups;
        this.end = this.start.plus({ [`${this.granularity}s`]: fillTemporalPeriod });
        this.computedEnd = true;
    }
    /**
     * @param {DateTime} bound the DateTime to be formatted (this.start or this.end)
     * @returns {string | false}
     */
    _getFormattedServerDate(bound) {
        if (this.field.type === "date") {
            return serializeDate(bound);
        } else {
            return serializeDateTime(bound);
        }
    }
    /**
     * @param {Object} configuration
     * @param {any[]} configuration.domain
     * @param {boolean} [configuration.forceStartBound=true] whether this.start DateTime must be
     *                                         used as a domain constraint to limit read_group
     *                                         results or not
     * @param {boolean} [configuration.forceEndBound=true] whether this.end DateTime must be used
     *                                       as a domain constraint to limit read_group results
     *                                       or not
     * @returns {any[]} new domain
     */
    getDomain({ domain, forceStartBound = true, forceEndBound = true }) {
        if (!forceEndBound && !forceStartBound) {
            return domain;
        }
        const originalDomain = domain.length ? ["&", ...domain] : [];
        const defaultDomain = ["|", [this.field.name, "=", false]];
        const linkDomain = forceStartBound && forceEndBound ? ["&"] : [];
        const startDomain = !forceStartBound
            ? []
            : [[this.field.name, ">=", this._getFormattedServerDate(this.start)]];
        const endDomain = !forceEndBound
            ? []
            : [[this.field.name, "<", this._getFormattedServerDate(this.end)]];
        return [
            ...originalDomain,
            ...defaultDomain,
            ...linkDomain,
            ...startDomain,
            ...endDomain,
        ];
    }
    /**
     * @param {Object} configuration
     * @param {Object} [configuration.context]
     * @param {boolean} [configuration.forceFillingFrom=true] fill_temporal must apply from:
     *                                          true: this.start
     *                                          false: the first group with at least one record
     * @param {boolean} [configuration.forceFillingTo=!this.computedEnd] fill_temporal must apply
     *                                          until:
     *                                          true: this.end
     *                                          false: the last group with at least one record
     * @returns {Record<string, any> & { fill_temporal: FillTemporalContext }} new context
     */
    getContext({
        context,
        forceFillingFrom = true,
        forceFillingTo = !this.computedEnd,
    }) {
        /** @type {FillTemporalContext} */
        const fillTemporal = {
            min_groups: this.minGroups,
        };
        if (forceFillingFrom) {
            fillTemporal.fill_from = this._getFormattedServerDate(this.start);
        }
        if (forceFillingTo) {
            const minGranularity = this.field.type === "date" ? "days" : "seconds";
            fillTemporal.fill_to = this._getFormattedServerDate(
                this.end.minus({ [minGranularity]: 1 }),
            );
        }
        return { ...context, fill_temporal: fillTemporal };
    }
    /**
     * @param {number} minGroups minimum amount of groups to display, regardless of other
     *                            constraints
     */
    setMinGroups(minGroups) {
        const next = minGroups || 1;
        if (next === this.minGroups) {
            return;
        }
        this.minGroups = next;
        if (this.computedEnd) {
            this._computeEnd();
        }
    }
    /**
     * @param {DateTime} end
     */
    setEnd(end) {
        this.end = luxon.DateTime.max(this.start, end);
        this.computedEnd = false;
    }
    /**
     * @returns {boolean} whether the anchor moved
     */
    refreshStart() {
        const start = GRANULARITY_TABLE[this.granularity].startOf(luxon.DateTime.now());
        if (start.equals(this.start)) {
            return false;
        }
        this.start = start;
        if (this.computedEnd) {
            this._computeEnd();
        } else {
            this.end = luxon.DateTime.max(this.start, this.end);
        }
        return true;
    }
    expand() {
        this.setEnd(this.end.plus({ [`${this.granularity}s`]: 1 }));
    }
}

export class FillTemporal {
    constructor() {
        /** @type {Map<string, FillTemporalPeriod>} */
        this._fillTemporalPeriods = new Map();
    }

    /**
     * @param {Object} configuration
     * @param {string} configuration.modelName directly taken from model.loadParams.modelName.
     *                             this is the `res_model` from the action (i.e. `crm.lead`)
     * @param {TemporalField} configuration.field a dictionary with keys "name" and "type".
     *                              name: name of the field on which the fill_temporal should
     *                              apply (i.e. 'date_deadline')
     *                              type: date field type: 'date' or 'datetime'
     * @param {string} configuration.granularity can either be : hour, day, week, month,
     *                              quarter, year
     * @param {number} [configuration.minGroups] minimal amount of desired groups;
     *                              omitted leaves a cached period's minimum untouched
     * @param {boolean} [configuration.forceRecompute=false] optional whether the fill_temporal
     *                                         period should be reinstancied
     * @returns {FillTemporalPeriod}
     */
    getFillTemporalPeriod({
        modelName,
        field,
        granularity,
        minGroups,
        forceRecompute = false,
    }) {
        const key = JSON.stringify([modelName, field.name, granularity]);
        let period = this._fillTemporalPeriods.get(key);
        if (!period || forceRecompute) {
            period = new FillTemporalPeriod(
                modelName,
                field,
                granularity,
                minGroups ?? DEFAULT_MIN_GROUPS,
            );
            this._fillTemporalPeriods.set(key, period);
            return period;
        }
        if (minGroups !== undefined) {
            period.setMinGroups(minGroups);
        }
        period.refreshStart();
        return period;
    }

    /**
     * @param {Object} configuration
     * @param {string} configuration.modelName
     * @param {string} configuration.groupBySpec a groupBy entry, i.e. "date_deadline:week"
     * @param {Record<string, any>} configuration.fields the model's field descriptors
     * @param {number} [configuration.minGroups]
     * @param {boolean} [configuration.forceRecompute]
     * @returns {FillTemporalPeriod}
     */
    getFillTemporalPeriodForGroupBy({
        modelName,
        groupBySpec,
        fields,
        minGroups,
        forceRecompute,
    }) {
        const [fieldName, granularity] = groupBySpec.split(":");
        const { name, type } = fields[fieldName];
        return this.getFillTemporalPeriod({
            modelName,
            field: { name, type },
            granularity: granularity || "month",
            minGroups,
            forceRecompute,
        });
    }
}

export const fillTemporalService = {
    /** @returns {FillTemporal} */
    start() {
        return new FillTemporal();
    },
};

registry.category("services").add("fillTemporalService", fillTemporalService);
