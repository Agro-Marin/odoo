// @ts-check
/** @odoo-module native */

/** @module @web/services/web_vitals/web_vitals_service */

import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { session } from "@web/session";

const ENDPOINT = "/web/observability/cwv";

let _pageviewCounter = 0;

export const webVitalsService = {
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

        /** @type {{ lcp?: number, fcp?: number, cls?: number, ttfb?: number, inp?: number }} */
        const metrics = {};

        const pageviewId =
            browser.crypto?.randomUUID?.() ??
            `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${++_pageviewCounter}`;

        const pageviewPath = browser.location.pathname;

        /** @type {PerformanceObserver[]} */
        const observers = [];

        try {
            const nav = /** @type {any} */ (
                browser.performance.getEntriesByType("navigation")[0]
            );
            if (nav && nav.responseStart > 0) {
                const activationStart = nav.activationStart || 0;
                metrics.ttfb = Math.max(0, nav.responseStart - activationStart);
            }
        } catch {}

        try {
            const fcpObserver = new browser.PerformanceObserver((entries) => {
                for (const entry of entries.getEntries()) {
                    if (entry.name === "first-contentful-paint") {
                        metrics.fcp = entry.startTime;
                        fcpObserver.disconnect();
                        break;
                    }
                }
            });
            fcpObserver.observe({ type: "paint", buffered: true });
            observers.push(fcpObserver);
        } catch {}

        try {
            const lcpObserver = new browser.PerformanceObserver((entries) => {
                const list = entries.getEntries();
                const last = list[list.length - 1];
                if (last) {
                    metrics.lcp = last.startTime;
                }
            });
            lcpObserver.observe({
                type: "largest-contentful-paint",
                buffered: true,
            });
            observers.push(lcpObserver);
        } catch {}

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
                metrics.cls = clsValue;
            });
            clsObserver.observe({ type: "layout-shift", buffered: true });
            observers.push(clsObserver);
            metrics.cls = 0;
        } catch {}

        try {
            const inpObserver = new browser.PerformanceObserver((entries) => {
                for (const entry of entries.getEntries()) {
                    const e = /** @type {any} */ (entry);
                    if (!e.interactionId) {
                        continue;
                    }
                    if (e.duration > (metrics.inp || 0)) {
                        metrics.inp = e.duration;
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
            observers.push(inpObserver);
        } catch {}

        let lastSentSignature = "";
        function flush() {
            const keys = Object.keys(metrics);
            if (!keys.length) {
                return;
            }
            const signature = JSON.stringify(metrics);
            if (signature === lastSentSignature) {
                return;
            }
            lastSentSignature = signature;
            try {
                const payload = {
                    url: pageviewPath,
                    user_agent: browser.navigator.userAgent.slice(0, 500),
                    pageview_id: pageviewId,
                    ...metrics,
                };
                const blob = new Blob([JSON.stringify(payload)], {
                    type: "application/json",
                });
                browser.navigator.sendBeacon(ENDPOINT, blob);
            } catch {}
        }

        const onPagehide = (/** @type {PageTransitionEvent} */ ev) => {
            flush();
            if (!ev.persisted) {
                for (const observer of observers) {
                    observer.disconnect();
                }
            }
        };
        const onVisibilityChange = () => {
            if (document.visibilityState === "hidden") {
                flush();
            }
        };
        browser.addEventListener("pagehide", onPagehide);
        browser.addEventListener("visibilitychange", onVisibilityChange);

        return {
            destroy() {
                browser.removeEventListener("pagehide", onPagehide);
                browser.removeEventListener("visibilitychange", onVisibilityChange);
                for (const observer of observers) {
                    observer.disconnect();
                }
            },
        };
    },
};

registry.category("services").add("web_vitals", webVitalsService);
