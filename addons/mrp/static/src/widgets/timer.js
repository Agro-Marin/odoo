/** @odoo-module native */
import {
    Component,
    onWillDestroy,
    onWillStart,
    onWillUpdateProps,
    useState,
} from "@odoo/owl";
import { parseFloatTime } from "@web/core/parsers";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useRecordObserver } from "@web/fields/hooks/record_observer";
import { useInputField } from "@web/fields/input_field_hook";
import { standardFieldProps } from "@web/fields/standard_field_props";

const LIVE_DURATION_FIELD = "duration_live";

function formatMinutes(value) {
    if (value === false) {
        return "";
    }
    const isNegative = value < 0;
    if (isNegative) {
        value = Math.abs(value);
    }
    let min = Math.floor(value);
    let sec = Math.round((value % 1) * 60);
    if (sec === 60) {
        min += 1;
        sec = 0;
    }
    sec = `${sec}`.padStart(2, "0");
    min = `${min}`.padStart(2, "0");
    return `${isNegative ? "-" : ""}${min}:${sec}`;
}

export class MrpTimer extends Component {
    static template = "mrp.MrpTimer";
    static props = {
        value: { type: Number },
        ongoing: { type: Boolean, optional: true },
    };
    static defaultProps = { ongoing: false };

    setup() {
        this.state = useState({
            duration: this.props.value,
        });
        this.lastDateTime = Date.now();
        this.ongoing = this.props.ongoing;
        onWillStart(() => {
            if (this.ongoing) {
                this._startTimers();
            }
        });
        onWillUpdateProps((nextProps) => {
            const rerun = !this.ongoing && nextProps.ongoing;
            this.ongoing = nextProps.ongoing;
            if (rerun) {
                this.state.duration = nextProps.value;
                this._startTimers();
            }
        });
        onWillDestroy(() => this._stopTimers());
    }

    get durationFormatted() {
        return formatMinutes(this.state.duration);
    }

    _startTimers() {
        this._stopTimers();
        this.lastDateTime = Date.now();
        this._runTimer();
        this._runSleepTimer();
    }

    _stopTimers() {
        clearTimeout(this._tickTimer);
        clearTimeout(this._sleepTimer);
    }

    _runTimer() {
        this._tickTimer = setTimeout(() => {
            if (this.ongoing) {
                this.state.duration += 1 / 60;
                this._runTimer();
            }
        }, 1000);
    }

    _runSleepTimer() {
        this._sleepTimer = setTimeout(() => {
            if (!this.ongoing) {
                return;
            }
            const diff = Date.now() - this.lastDateTime - 10000;
            if (diff > 1000) {
                this.state.duration += diff / (1000 * 60);
            }
            this.lastDateTime = Date.now();
            this._runSleepTimer();
        }, 10000);
    }
}

class MrpTimerField extends Component {
    static template = "mrp.MrpTimerField";
    static components = { MrpTimer };
    static props = standardFieldProps;

    setup() {
        this.orm = useService("orm");
        useInputField({
            getValue: () => this.durationFormatted,
            refName: "numpadDecimal",
            parse: (v) => parseFloatTime(v),
        });

        useRecordObserver(async (record) => {
            this.duration = await this.getLiveDuration(record);
        });
    }

    async getLiveDuration(record) {
        if (record.model.useSampleModel || record.data.state !== "progress") {
            return record.data[this.props.name];
        }
        if (LIVE_DURATION_FIELD in record.data) {
            return record.data[LIVE_DURATION_FIELD];
        }
        return this.orm.call("mrp.workorder", "get_duration", [record.resId]);
    }

    get durationFormatted() {
        if (
            this.props.record.data[this.props.name] !== this.duration &&
            this.props.record.dirty
        ) {
            this.duration = this.props.record.data[this.props.name];
        }
        return formatMinutes(this.duration);
    }

    get ongoing() {
        return this.props.record.data.is_user_working;
    }
}

export const mrpTimerField = {
    component: MrpTimerField,
    supportedTypes: ["float"],
};

registry.category("fields").add("mrp_timer", mrpTimerField);
registry.category("formatters").add("mrp_timer", formatMinutes);
