/**
 * ESM wrapper for Chart.js UMD.
 *
 * Dynamically loads the self-contained UMD build which sets
 * ``globalThis.Chart``, then re-exports it as named ESM exports.
 * This allows native modules to ``await import(...)`` Chart.js
 * without needing the legacy ``loadBundle()`` mechanism.
 */

// Ensure the UMD is loaded (idempotent — script tag deduplicates)
if (!globalThis.Chart) {
    await new Promise((resolve, reject) => {
        const script = document.createElement("script");
        script.src = "/web/static/lib/Chart/Chart.js";
        script.onload = resolve;
        script.onerror = reject;
        document.head.appendChild(script);
    });
}

const Chart = globalThis.Chart;
export { Chart };
export default Chart;
