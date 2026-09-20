/** @odoo-module native */
/**
 * @param {string} url1
 * @param {string} url2
 * @returns {Boolean}
 */
export function isHTTPSorNakedDomainRedirection(url1, url2) {
    try {
        url1 = new URL(url1).host;
        url2 = new URL(url2).host;
    } catch {
        return false;
    }
    return url1 === url2 || url1.replace(/^www\./, "") === url2.replace(/^www\./, "");
}
