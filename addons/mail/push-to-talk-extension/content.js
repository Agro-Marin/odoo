/* global chrome */

const EXT_ID = "mdiacebcbkmjjlpclnbcgiepgifcnpmg";

chrome.runtime.onMessage.addListener(function (request, sender) {
    if (location.origin !== "null" && sender.id === EXT_ID) {
        window.postMessage(request, location.origin);
    }
});
