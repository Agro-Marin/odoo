/** @odoo-module native */
import { loadPDFJS } from "@web/core/utils/pdfjs";
export async function generatePdfThumbnail(
    pdfUrl,
    options = { height: 256, width: 256 },
) {
    let isPdfValid, pdf, pdfjsLib, thumbnail, loadingTask;
    try {
        // The loader sets GlobalWorkerOptions.workerSrc centrally, so
        // rendering runs in a real worker instead of hanging the tab.
        pdfjsLib = await loadPDFJS();
    } catch {
        return { isPdfValid: false, thumbnail, pdfEnabled: false };
    }
    try {
        // pdfjs' getDocument accepts a URL string directly, including a
        // "blob:" object URL. (The previous blob branch wrapped the string in
        // URL.createObjectURL(), which requires a Blob and threw for every
        // blob URL, silently blanking the thumbnail.)
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
            // Render first page onto a canvas
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
        // Release the parsed document and its worker port. pdfjs never reclaims
        // the PDFDocumentProxy on its own, so each thumbnail generated (one per
        // writable PDF attachment lacking a thumbnail) leaked its parsed data.
        await loadingTask?.destroy();
    }
    return { isPdfValid, thumbnail, pdfEnabled: true };
}
