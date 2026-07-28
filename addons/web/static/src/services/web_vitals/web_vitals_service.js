// @ts-check
/** @odoo-module native */

/** @module @web/services/web_vitals/web_vitals_service - Real User Monitoring (RUM) for Core Web Vitals via sendBeacon on pagehide */

import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { session } from "@web/session";

const ENDPOINT = "/web/observability/cwv";

let _pageviewCounter = 0;

/**
 * Service that captures Core Web Vitals via PerformanceObserver and beacons
 * them to the server when the page is hidden or unloaded.  Reuses the
 * ``pagehide`` + ``navigator.sendBeacon`` pattern proven in
 * ``record_save.js`` (``save()``) for urgent saves.
 *
 * Captures: LCP (Largest Contentful Paint), FCP (First Contentful Paint),
 * CLS (Cumulative Layout Shift), TTFB (Time To First Byte), and INP
 * (Interaction to Next Paint — reported as the worst-observed interaction
 * duration; see the P100-vs-P98 note near the INP observer below).
 */
export const webVitalsService = {
    /** Service has no dependencies; runs once at startup, then passively observes. */
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
        } catch {
            // ignore — browser without nav-timing v2 (very rare)
        }

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
        } catch {
            // ignore — browser without paint timing
        }

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
        } catch {
            // ignore
        }

        try {
            // CLS is the LARGEST session window, not the lifetime total: a
            // window is a burst of shifts each within 1s of the previous and
            // spanning at most 5s. Summing every shift instead (what this did)
            // is unbounded in a single-page app whose session lasts hours, and
            // the server-side `_clamp_cls` in `controllers/observability.py`
            // DROPS anything above 5.0 — so a long session silently stopped
            // reporting CLS at all, while shorter ones over-reported it.
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
                // Assigned unconditionally, not only when the max grows: a page
                // whose every shift was input-triggered must still report
                // `cls: 0` ("measured, and it was perfect") rather than omit the
                // key, which reads downstream as "not measured".
                metrics.cls = clsValue;
            });
            clsObserver.observe({ type: "layout-shift", buffered: true });
            observers.push(clsObserver);
        } catch {
            // ignore
        }

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
        } catch {
            // ignore — Safari ≤16 ships event-timing without ``interactionId``
            // (lands in 16.4); pre-Chromium-96 lacks the entry type entirely.
        }

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
            } catch {
                // RUM must never throw into user code.  Drop silently.
            }
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
            /**
             * Release the window listeners and the PerformanceObservers. The
             * page-lived production env is never torn down, but an embedded or
             * sub-app env is: without this, its observers keep collecting and
             * its `pagehide` handler keeps beaconing a dead env's metrics.
             */
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
