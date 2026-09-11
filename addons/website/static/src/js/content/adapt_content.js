/** @odoo-module native */
document.addEventListener("DOMContentLoaded", () => {
    const htmlEl = document.documentElement;
    const editTranslations = !!htmlEl.dataset.edit_translations;
    if (editTranslations) {
        [...document.querySelectorAll("textarea")].map((textarea) => {
            if (textarea.value.indexOf("data-oe-translation-source-sha") !== -1) {
                textarea.classList.add("o_text_content_invisible");
            }
        });
    }
    const searchModalEl = document.querySelector("header#top .modal#o_search_modal");
    if (searchModalEl) {
        const mainEl = document.querySelector("main");
        const searchDivEl = document.createElement("div");
        searchDivEl.id = "o_search_modal_block";
        searchDivEl.appendChild(searchModalEl);
        mainEl.appendChild(searchDivEl);
    }
});
