// @odoo-module ignore

(function () {
    "use strict";

    document.addEventListener("DOMContentLoaded", () => {
        var textareaEls = document.querySelectorAll("textarea.o_wysiwyg_loader");
        for (var i = 0; i < textareaEls.length; i++) {
            var textarea = textareaEls[i];
            var wrapper = document.createElement("div");
            wrapper.classList.add("position-relative", "o_wysiwyg_textarea_wrapper");

            var loadingElement = document.createElement("div");
            loadingElement.classList.add("o_wysiwyg_loading");
            var loadingIcon = document.createElement("i");
            loadingIcon.classList.add(
                "text-600",
                "text-center",
                "fa",
                "fa-circle-o-notch",
                "fa-spin",
                "fa-2x",
            );
            loadingElement.appendChild(loadingIcon);
            wrapper.appendChild(loadingElement);

            textarea.parentNode.insertBefore(wrapper, textarea);
            wrapper.insertBefore(textarea, loadingElement);
        }
    });
})();
