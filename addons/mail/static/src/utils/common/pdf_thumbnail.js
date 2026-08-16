/** @odoo-module native */
import { loadPDFJS } from "@web/core/utils/pdfjs";
/**
 * @param {string} pdfUrl
 * @param {Object} [options]
 * @param {number} [options.height=256]
 * @param {number} [options.width=256]
 * @returns {Promise<{isPdfValid: boolean|undefined, thumbnail: string|undefined, pdfEnabled?: boolean}>}
 */
export async function generatePdfThumbnail(
    pdfUrl,
    options = { height: 256, width: 256 },
) {
    let isPdfValid, pdf, pdfjsLib, thumbnail, loadingTask;
    try {
        pdfjsLib = await loadPDFJS();
    } catch {
        return { isPdfValid: false, thumbnail, pdfEnabled: false };
    }
    try {
        loadingTask = pdfjsLib.getDocument(pdfUrl);
        pdf = await loadingTask.promise;
    } catch (_error) {
        if (_error.status === 415) {
            isPdfValid = false;
        }
    }
    try {
        if (pdf) {
            isPdfValid = true;
            const page = await pdf.getPage(1);
            const viewPort = page.getViewport({ scale: 1 });
            const canvas = document.createElement("canvas");
            canvas.width = options.width;
            canvas.height = options.height;
            const scale = canvas.width / viewPort.width;
            await page.render({
                canvasContext: canvas.getContext("2d"),
                viewport: page.getViewport({ scale }),
            }).promise;
            thumbnail = canvas
                .toDataURL("image/jpeg")
                .replace("data:image/jpeg;base64,", "");
        }
    } finally {
        await loadingTask?.destroy();
    }
    return { isPdfValid, thumbnail, pdfEnabled: true };
}
