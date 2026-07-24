/** @odoo-module native */
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";
import { initZoomOdoo } from "@website/libs/zoomodoo/zoomodoo";

/**
 * Page-global website behaviors, historically installed by the legacy
 * WebsiteRoot widget: language switch links, publish toggle buttons, the
 * `modal_shown` marker class (relied upon by tours) and image zoom.
 *
 * Listeners are delegated on `document.body` (not the interaction root):
 * modals and language switchers may live outside #wrapwrap, as they did when
 * the legacy root was attached to the body.
 */
export class WebsitePage extends Interaction {
    static selector = "#wrapwrap";

    start() {
        this.addListener(document.body, "click", (ev) => {
            const langEl = ev.target.closest(".js_change_lang");
            if (langEl) {
                return this._onLangChangeClick(ev, langEl);
            }
            const publishEl = ev.target.closest(
                ".js_publish_management .js_publish_btn",
            );
            if (publishEl) {
                return this._onPublishBtnClick(ev, publishEl);
            }
        });
        this.addListener(document.body, "shown.bs.modal", (ev) => {
            ev.target.classList.add("modal_shown");
        });

        // Enable magnify on zoomable img
        for (const imgEl of document.body.querySelectorAll(
            ".zoomable img[data-zoom]",
        )) {
            initZoomOdoo(imgEl);
        }
    }

    //--------------------------------------------------------------------------
    // Handlers
    //--------------------------------------------------------------------------

    /**
     * @param {MouseEvent} ev
     * @param {HTMLElement} target
     */
    _onLangChangeClick(ev, target) {
        ev.preventDefault();
        // In edit mode, the client action redirects the iframe to the correct
        // location with the chosen language.
        if (document.body.classList.contains("editor_enable")) {
            return;
        }
        // retrieve the hash before the redirect
        const redirect = {
            lang: encodeURIComponent(target.dataset.urlCode),
            url: encodeURIComponent(
                target.getAttribute("href").replace(/[&?]edit_translations[^&?]+/, ""),
            ),
            hash: encodeURIComponent(window.location.hash),
        };
        window.location.href = `/website/lang/${redirect.lang}?r=${redirect.url}${redirect.hash}`;
    }

    /**
     * @param {MouseEvent} ev
     * @param {HTMLElement} target
     */
    _onPublishBtnClick(ev, target) {
        ev.preventDefault();
        if (document.body.classList.contains("editor_enable")) {
            return;
        }

        const publishEl = target.closest(".js_publish_management");
        this.services.orm
            .call(publishEl.dataset.object, "website_publish_button", [
                [parseInt(publishEl.dataset.id, 10)],
            ])
            .then(function (result) {
                publishEl.classList.toggle("css_published", result);
                publishEl.classList.toggle("css_unpublished", !result);
                const itemEl = publishEl.closest("[data-publish]");
                if (itemEl) {
                    itemEl.dataset.publish = result ? "on" : "off";
                }
            });
    }
}

registry.category("public.interactions").add("website.website_page", WebsitePage);
