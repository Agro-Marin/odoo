// @ts-check
/** @odoo-module native */

/** @module @web/views/calendar/calendar_renderer */

import { Component } from "@odoo/owl";
import { ActionSwiper } from "@web/components/action_swiper/action_swiper";
import { useReactiveModel } from "@web/model/model";

import { CalendarCommonRenderer } from "./calendar_common/calendar_common_renderer.js";
import { CalendarYearRenderer } from "./calendar_year/calendar_year_renderer.js";
export class CalendarRenderer extends Component {
    static template = "web.CalendarRenderer";
    static components = {
        day: CalendarCommonRenderer,
        week: CalendarCommonRenderer,
        month: CalendarCommonRenderer,
        year: CalendarYearRenderer,
        ActionSwiper,
    };
    static props = {
        model: Object,
        isWeekendVisible: Boolean,
        createRecord: Function,
        editRecord: Function,
        deleteRecord: Function,
        setDate: Function,
        callbackRecorder: Object,
        onSquareSelection: Function,
        cleanSquareSelection: Function,
    };
    setup() {
        // Subscribe to the model rather than reading it off the raw prop, so a
        // `notify()` re-renders this component on its own instead of relying on
        // the controller's blanket deep render.
        this.model = useReactiveModel(this.props.model);
    }

    get concreteRenderer() {
        return /** @type {any} */ (this.constructor).components[this.model.scale];
    }
    get concreteRendererProps() {
        if (this.model.scale === "year") {
            return {
                model: this.model,
                isWeekendVisible: this.props.isWeekendVisible,
                createRecord: this.props.createRecord,
                editRecord: this.props.editRecord,
                deleteRecord: this.props.deleteRecord,
            };
        }
        return this.props;
    }
    get calendarKey() {
        return this.model.scale;
    }
    get actionSwiperProps() {
        return {
            onLeftSwipe: this.env.isSmall
                ? { action: () => this.props.setDate("next") }
                : undefined,
            onRightSwipe: this.env.isSmall
                ? { action: () => this.props.setDate("previous") }
                : undefined,
            animationOnMove: false,
            animationType: "forwards",
            swipeDistanceRatio: 6,
            swipeInvalid: () => Boolean(document.querySelector(".o_event.fc-mirror")),
        };
    }
}
