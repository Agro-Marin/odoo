/** @odoo-module native */
import { loadPDFJS } from "@web/core/utils/pdfjs";
export async function generatePdfThumbnail(
    pdfUrl,
    options = { height: 256, width: 256 },
) {
    let isPdfValid, pdf, pdfjsLib, thumbnail;
    try {
        // The loader sets GlobalWorkerOptions.workerSrc centrally, so
        // rendering runs in a real worker instead of hanging the tab.
        pdfjsLib = await loadPDFJS();
    } catch {
        return { thumbnail, pdfEnabled: false };
    }
    try {
        // pdfjs' getDocument accepts a URL string directly, including a
        // "blob:" object URL. (The previous blob branch wrapped the string in
        // URL.createObjectURL(), which requires a Blob and threw for every
        // blob URL, silently blanking the thumbnail.)
        pdf = await pdfjsLib.getDocument(pdfUrl).promise;
    } catch (_error) {
        if (_error.status === 415) {
            isPdfValid = false;
        }
    }
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
    return { isPdfValid, thumbnail, pdfEnabled: true };
}
