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
 */

/**
 * Configuration depending on the granularity, using Luxon DateTime objects:
 * `startOf` gets a DateTime at the beginning of a period from another DateTime.
 * `cycle` is the amount of 'granularity' periods constituting a cycle. The cycle duration
 * is arbitrary for each granularity:
 * cycle    ---    granularity
 * ___________________________
 * 1 day           hour
 * 1 week          day
 * 1 week          week    # there is no greater time period that takes an integer amount of weeks
 * 1 year          month
 * 1 year          quarter
 * 1 year          year    # we are not using a greater time period in Odoo (yet)
 * `cyclePos` gets the position (index) in the cycle from a DateTime.
 * {1} is the first index. {+1} is used for properties which have an index
 * starting from 0, to standardize between granularities.
 *
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

/**
 * fill_temporal period:
 *   Represents a specific date/time range for a specific model, field and granularity.
 *
 * It is used to add new domain and context constraints related to a specific date/time
 * field, in order to configure the _read_group_fill_temporal (see core models.py)
 * method. It will be used when we want to get continuous groups in chronological
 * order in a specific date/time range.
 */
const DEFAULT_MIN_GROUPS = 4;

export class FillTemporalPeriod {
    /**
     * Assigned by the helpers the constructor calls, which is a sequence
     * TypeScript cannot follow, so the fields are declared.
     *
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
     * This constructor is meant to be used only by the FillTemporalService (see below)
     *
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
     * Compute this.start: the DateTime for the start of the period containing
     * the current time ("now").
     * i.e. 2020-10-01 13:43:17 -> the current "hour" DateTime started at:
     *      2020-10-01 13:00:00
     *
     * @private
     */
    _computeStart() {
        this.start = GRANULARITY_TABLE[this.granularity].startOf(luxon.DateTime.now());
    }
    /**
     * Compute this.end: the DateTime for the end of the fill_temporal period.
     * This bound is exclusive.
     * The fill_temporal period is the number of [granularity] from [start] to the end of the
     * [cycle] reached after adding [minGroups]
     * i.e. we are in october 2020 :
     *      [start] = 2020-10-01
     *      [granularity] = 'month',
     *      [cycle] = 12
     *      [minGroups] = 4,
     *      => fillTemporalPeriod = 15 months (until end of december 2021)
     *
     * @private
     */
    _computeEnd() {
        const cycle = GRANULARITY_TABLE[this.granularity].cycle;
        const cyclePos = GRANULARITY_TABLE[this.granularity].cyclePos(this.start);
        // fillTemporalPeriod formula explanation :
        // We want to know how many steps need to be taken from the current position until the end
        // of the cycle reached after guaranteeing minGroups positions. Let's call this cycle (C).
        //
        // (1) compute the steps needed to reach the last position of the current cycle, from the
        //     current position:
        //     {cycle - cyclePos}
        //
        // (2) ignore {minGroups - 1} steps from the position reached in (1). Now, the current
        //     position is somewhere in (C). One step from minGroups is reserved to reach the first
        //     position after (C), hence {-1}
        //
        // (3) compute the additional steps needed to reach the last position of (C), from the
        //     position reached in (2):
        //     {cycle - (minGroups - 1) % cycle}
        //
        // (4) combine (1) and (3), the sum should not be greater than a full cycle (-> truncate):
        //     {(2 * cycle - (minGroups - 1) % cycle - cyclePos) % cycle}
        //
        // (5) add minGroups!
        const fillTemporalPeriod =
            ((2 * cycle - ((this.minGroups - 1) % cycle) - cyclePos) % cycle) +
            this.minGroups;
        this.end = this.start.plus({ [`${this.granularity}s`]: fillTemporalPeriod });
        this.computedEnd = true;
    }
    /**
     * The server needs a date/time in UTC, but we don't want a day shift in case
     * of dates, even if the date is not in UTC
     *
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
     * The default value of forceFillingTo is false when this.end is the
     * computed one, and true when it is manually set. This is because the default value of
     * this.end is computed without any knowledge of the existing data, and as such, we only
     * want to get continuous groups until the last group with data (no need to force until
     * this.end). On the contrary, when we set this.end, this means that we want groups until
     * that date.
     *
     * @param {Object} configuration
     * @param {Object} [configuration.context]
     * @param {boolean} [configuration.forceFillingFrom=true] fill_temporal must apply from:
     *                                          true: this.start
     *                                          false: the first group with at least one record
     * @param {boolean} [configuration.forceFillingTo=!this.computedEnd] fill_temporal must apply
     *                                          until:
     *                                          true: this.end
     *                                          false: the last group with at least one record
     * @returns {Object} new context
     */
    getContext({
        context,
        forceFillingFrom = true,
        forceFillingTo = !this.computedEnd,
    }) {
        /**
         * @type {{
         *     min_groups: number,
         *     fill_from?: string | false,
         *     fill_to?: string | false,
         * }}
         */
        const fillTemporal = {
            min_groups: this.minGroups,
        };
        if (forceFillingFrom) {
            fillTemporal.fill_from = this._getFormattedServerDate(this.start);
        }
        if (forceFillingTo) {
            // smallest time interval used in Odoo for the current date type
            const minGranularity = this.field.type === "date" ? "days" : "seconds";
            fillTemporal.fill_to = this._getFormattedServerDate(
                this.end.minus({ [minGranularity]: 1 }),
            );
        }
        context = { ...context, fill_temporal: fillTemporal };
        return context;
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
     * sets the end of the period to the desired DateTime. It must be greater
     * than start. Changes the default behavior of getContext forceFillingTo
     * (becomes true instead of false)
     *
     * @param {DateTime} end
     */
    setEnd(end) {
        this.end = luxon.DateTime.max(this.start, end);
        this.computedEnd = false;
    }
    /**
     * Re-anchor the period on the granularity period containing "now".
     *
     * The constructor reads the clock once, and the service caches the instance
     * for the whole session, so without this a view left mounted across a period
     * boundary keeps sending the start it was built with. A derived end is
     * recomputed with it; an end that was set deliberately (setEnd / expand, or
     * the last group with data) is kept and only clamped to stay >= start.
     *
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
    /**
     * Adds one "granularity" period to [this.end], to expand the current fill_temporal period
     */
    expand() {
        this.setEnd(this.end.plus({ [`${this.granularity}s`]: 1 }));
    }
}

/**
 * fill_temporal Service
 *
 * This service will be used to generate or retrieve fill_temporal periods
 *
 * It lived in `crm` until 2026-08-28, which put the client half of a CORE ORM
 * feature -- `_read_group_fill_temporal`, in odoo/orm/models/mixins/read_group/
 * -- inside a business addon, so any other module wanting continuous temporal
 * grouping had to depend on crm to get it. Nothing in the module is about
 * leads: `getFillTemporalPeriod` takes the model name as an argument, and
 * `graph_model.js` two directories away already sets `fill_temporal` in its own
 * context. Its only consumer is still crm's forecast views, which reach it
 * through the service registry and needed no import change.
 *
 * A specific fill_temporal period configuration will always refer to the same instance
 * unless forceRecompute is true
 */
export class FillTemporal {
    constructor() {
        /** @type {Map<string, FillTemporalPeriod>} */
        this._fillTemporalPeriods = new Map();
    }

    /**
     * Get a fill_temporal period according to the configuration.
     * The default initial fill_temporal period is the number of [granularity] from [start]
     * to the end of the [cycle] reached after adding [minGroups]
     * i.e. we are in october 2020 :
     *      [start] = 2020-10-01
     *      [granularity] = 'month',
     *      [cycle] = 12 (one year)
     *      [minGroups] = 4,
     *      => fillTemporalPeriod = 15 months (until the end of december 2021)
     * Once created, a fill_temporal period for a specific configuration will be stored
     * until requested again. This allows to manipulate the period and store the changes
     * to it. This also allows to keep the configuration when switching to another view
     *
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
        // Only a caller that actually supplied a minimum may move it: callers
        // that do not care must not silently reset one that was configured.
        if (minGroups !== undefined) {
            period.setMinGroups(minGroups);
        }
        period.refreshStart();
        return period;
    }

    /**
     * Resolve the period for a groupBy spec, deriving the cache key from the spec
     * itself.
     *
     * This is the entry point every caller should use. The key is
     * (model, field, granularity), and callers that assembled it themselves did
     * not agree: crm's forecast model split the spec, while its renderer read a
     * `granularity` property off the field descriptor -- which no field has, so
     * it always resolved to "month" and expanded a period the model never read.
     * Deriving the key in one place is what makes that class of bug unwritable.
     *
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
