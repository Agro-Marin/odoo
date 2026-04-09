/** @odoo-module native */
import { loadPDFJSAssets } from "@web/core/utils/pdfjs";
export async function generatePdfThumbnail(
    pdfUrl,
    options = { height: 256, width: 256 },
) {
    let isPdfValid,
        pdf,
        thumbnail;
    let pdfjsLib;
    try {
        pdfjsLib = await loadPDFJSAssets();
    } catch {
        return { thumbnail, pdfEnabled: false };
    }
    try {
        // Support for blob url
        if (pdfUrl.startsWith("blob:")) {
            pdfUrl = URL.createObjectURL(pdfUrl);
            pdf = await pdfjsLib.getDocument(pdfUrl).promise;
            URL.revokeObjectURL(pdfUrl);
        } else {
            pdf = await pdfjsLib.getDocument(pdfUrl).promise;
        }
    } catch (_error) {
        if (_error.status === 415) {
            isPdfValid = false;
        } else if (
            _error.name !== "UnexpectedResponseException" &&
            _error.status &&
            _error.status !== 403
        ) {
            pdf = undefined;
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
