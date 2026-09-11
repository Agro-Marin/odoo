/** @odoo-module native */
import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

export class DisplayTimer extends Interaction {
    static selector = ".o_display_timer";
    dynamicContent = {
        "span.o_timer_days": { "t-out": () => this.daysText },
        "span.o_timer_hours": { "t-out": () => this.hoursText },
        "span.o_timer_minutes": { "t-out": () => this.minutesText },
        "span.o_timer_seconds": { "t-out": () => this.secondsText },
    };

    setup() {
        const options = this.el.dataset;

        this.preCountdownTime = parseInt(options["preCountdownTime"]);
        this.mainCountdownTime = parseInt(options["mainCountdownTime"]);
        this.mainCountdownText = options["mainCountdownText"];
        this.hasMainTimeDisplay = options["mainCountdownDisplay"] === "true";

        this.displayClass = options["displayClass"];

        if (options["preCountdownDisplay"] === "true") {
            this.el.parentElement.classList.remove("d-none");
        }

        this.checkTimer();
        this.interval = setInterval(() => {
            this.checkTimer();
        }, 1000);
        this.registerCleanup(() => clearInterval(this.interval));
    }

    checkTimer() {
        const now = new Date();

        const remainingPreSeconds = this.preCountdownTime - now.getTime() / 1000;
        if (remainingPreSeconds <= 1) {
            const countdownTextEl = this.el.querySelector(".o_countdown_text");
            if (countdownTextEl) {
                countdownTextEl.textContent = this.mainCountdownText;
            }
            if (this.hasMainTimeDisplay) {
                this.el.parentElement.classList.remove("d-none");
            }
            const remainingMainSeconds = this.mainCountdownTime - now.getTime() / 1000;
            if (remainingMainSeconds <= 1) {
                clearInterval(this.interval);
                document.querySelector(this.displayClass).classList.remove("d-none");
                this.el.parentElement.classList.add("d-none");
            } else {
                this.updateCountdown(remainingMainSeconds);
            }
        } else {
            this.updateCountdown(remainingPreSeconds);
        }
    }

    /**
     * @param {number} remainingTime
     */
    updateCountdown(remainingTime) {
        let remainingSeconds = remainingTime;
        this.daysText = Math.floor(remainingSeconds / 86400).toString();

        remainingSeconds = remainingSeconds % 86400;
        this.hoursText = this.formatTime(Math.floor(remainingSeconds / 3600));

        remainingSeconds = remainingSeconds % 3600;
        this.minutesText = this.formatTime(Math.floor(remainingSeconds / 60));

        this.secondsText = this.formatTime(Math.floor(remainingSeconds % 60));
    }

    /**
     * @param {number} num
     */
    formatTime(num) {
        return (num < 10 ? "0" : "") + num;
    }
}

registry
    .category("public.interactions")
    .add("website_event.display_timer", DisplayTimer);
