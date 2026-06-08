// ESM facade over the vendored Chart.js v4 UMD bundle.
//
// The upstream distribution ships only ``Chart.js`` (a UMD bundle that, when
// loaded as a classic ``<script>``, assigns ``window.Chart``). That path is
// used by the manifest entry ``web.chartjs_lib``.
//
// Several Enterprise dashboards (hr_payroll, esg, sale_commission, equity,
// marketing_automation) reach for the library via a dynamic ``import()`` at
// this URL instead. ES modules parse the UMD source with module-scoped
// semantics, so the global assignment never escapes and ``import {Chart}``
// from this URL would return ``undefined``.
//
// This facade closes the gap: it loads the UMD bundle through a classic-script
// tag (which DOES assign to the global), waits for it to evaluate, and
// re-exports the public surface so dynamic-import callers get the same
// ``Chart`` constructor that classic-script callers receive.
if (!globalThis.Chart) {
    await new Promise((resolve, reject) => {
        const script = document.createElement("script");
        script.src = new URL("./Chart.js", import.meta.url).href;
        script.onload = resolve;
        script.onerror = () => reject(new Error("Failed to load Chart.js"));
        document.head.appendChild(script);
    });
}
export const Chart = globalThis.Chart;
export default Chart;
