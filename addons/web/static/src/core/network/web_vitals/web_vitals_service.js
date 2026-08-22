// @ts-check
/** @odoo-module native */

import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { session } from "@web/session";

const ENDPOINT = "/web/observability/cwv";

let _pageviewCounter = 0;

class WebVitalsService {
    constructor() {
        /** @type {{ lcp?: number, fcp?: number, cls?: number, ttfb?: number, inp?: number }} */
        this.metrics = {};
        this.pageviewId =
            browser.crypto?.randomUUID?.() ??
            `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${++_pageviewCounter}`;
        this.pageviewPath = browser.location.pathname;
        /** @type {PerformanceObserver[]} */
        this.observers = [];
        this.lastSentSignature = "";

        this.collectTtfb();
        this.observeFcp();
        this.observeLcp();
        this.observeCls();
        this.observeInp();

        this._onPagehide = (/** @type {any} */ ev) => this.onPagehide(ev);
        this._onVisibilityChange = () => this.onVisibilityChange();
        browser.addEventListener("pagehide", this._onPagehide);
        browser.addEventListener("visibilitychange", this._onVisibilityChange);
    }

    collectTtfb() {
        try {
            const nav = /** @type {any} */ (
                browser.performance.getEntriesByType("navigation")[0]
            );
            if (nav && nav.responseStart > 0) {
                const activationStart = nav.activationStart || 0;
                this.metrics.ttfb = Math.max(0, nav.responseStart - activationStart);
            }
        } catch {}
    }

    observeFcp() {
        try {
            const fcpObserver = new browser.PerformanceObserver((entries) => {
                for (const entry of entries.getEntries()) {
                    if (entry.name === "first-contentful-paint") {
                        this.metrics.fcp = entry.startTime;
                        fcpObserver.disconnect();
                        break;
                    }
                }
            });
            fcpObserver.observe({ type: "paint", buffered: true });
            this.observers.push(fcpObserver);
        } catch {}
    }

    observeLcp() {
        try {
            const lcpObserver = new browser.PerformanceObserver((entries) => {
                const list = entries.getEntries();
                const last = list[list.length - 1];
                if (last) {
                    this.metrics.lcp = last.startTime;
                }
            });
            lcpObserver.observe({
                type: "largest-contentful-paint",
                buffered: true,
            });
            this.observers.push(lcpObserver);
        } catch {}
    }

    observeCls() {
        try {
            let clsValue = 0;
            let windowValue = 0;
            let windowFirstMs = 0;
            let windowLastMs = 0;
            const clsObserver = new browser.PerformanceObserver((entries) => {
                for (const entry of entries.getEntries()) {
                    const e = /** @type {any} */ (entry);
                    if (e.hadRecentInput) {
                        continue;
                    }
                    const inSameWindow =
                        windowValue > 0 &&
                        e.startTime - windowLastMs < 1000 &&
                        e.startTime - windowFirstMs < 5000;
                    if (inSameWindow) {
                        windowValue += e.value;
                    } else {
                        windowValue = e.value;
                        windowFirstMs = e.startTime;
                    }
                    windowLastMs = e.startTime;
                    clsValue = Math.max(clsValue, windowValue);
                }
                this.metrics.cls = clsValue;
            });
            clsObserver.observe({ type: "layout-shift", buffered: true });
            this.observers.push(clsObserver);
            this.metrics.cls = 0;
        } catch {}
    }

    observeInp() {
        try {
            const inpObserver = new browser.PerformanceObserver((entries) => {
                for (const entry of entries.getEntries()) {
                    const e = /** @type {any} */ (entry);
                    if (!e.interactionId) {
                        continue;
                    }
                    if (e.duration > (this.metrics.inp || 0)) {
                        this.metrics.inp = e.duration;
                    }
                }
            });
            inpObserver.observe(
                /** @type {any} */ ({
                    type: "event",
                    buffered: true,
                    durationThreshold: 40,
                }),
            );
            this.observers.push(inpObserver);
        } catch {}
    }

    flush() {
        const keys = Object.keys(this.metrics);
        if (!keys.length) {
            return;
        }
        const signature = JSON.stringify(this.metrics);
        if (signature === this.lastSentSignature) {
            return;
        }
        this.lastSentSignature = signature;
        try {
            const payload = {
                url: this.pageviewPath,
                user_agent: browser.navigator.userAgent.slice(0, 500),
                pageview_id: this.pageviewId,
                ...this.metrics,
            };
            const blob = new Blob([JSON.stringify(payload)], {
                type: "application/json",
            });
            browser.navigator.sendBeacon(ENDPOINT, blob);
        } catch {}
    }

    /**
     * @param {PageTransitionEvent} ev
     */
    onPagehide(ev) {
        this.flush();
        if (!ev.persisted) {
            for (const observer of this.observers) {
                observer.disconnect();
            }
        }
    }

    onVisibilityChange() {
        if (document.visibilityState === "hidden") {
            this.flush();
        }
    }

    destroy() {
        browser.removeEventListener("pagehide", this._onPagehide);
        browser.removeEventListener("visibilitychange", this._onVisibilityChange);
        for (const observer of this.observers) {
            observer.disconnect();
        }
    }
}

export const webVitalsService = {
    /**
     * @returns {WebVitalsService | undefined}
     */
    start() {
        if (!browser.PerformanceObserver) {
            return;
        }
        const rawRate = Number(session.cwv_sample_rate);
        const sampleRate = Number.isFinite(rawRate)
            ? Math.max(0, Math.min(1, rawRate))
            : 1;
        if (sampleRate < 1 && Math.random() >= sampleRate) {
            return;
        }
        return new WebVitalsService();
    },
};

registry.category("services").add("web_vitals", webVitalsService);
