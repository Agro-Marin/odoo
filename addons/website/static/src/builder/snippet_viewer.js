/** @odoo-module native */
import { SnippetViewer } from "@html_builder/snippets/snippet_viewer";
import { onMounted, onPatched, onWillPatch, onWillUnmount } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";

const log = makeLogger("website.builder.snippet_viewer");

patch(SnippetViewer.prototype, {
    setup() {
        super.setup();
        useLifecycleLog(log);

        if (this.props.snippetModel.snippetsName === "website.snippets") {
            this.websiteService = useService("website");
            this.innerWebsiteEditService =
                this.websiteService.websitePublicEnv?.services["website_edit"];
            this.previousSearch = "";
            log.logic("SnippetViewer website snippets preview", () => ({
                hasWebsiteEdit: !!this.innerWebsiteEditService,
            }));

            const updatePreview = () => {
                if (this.innerWebsiteEditService) {
                    log.lifecycle("SnippetViewer preview interactions start");
                    this.innerWebsiteEditService.update(this.content.el, "preview");
                }
            };
            const stopPreview = () => {
                if (this.innerWebsiteEditService) {
                    log.lifecycle("SnippetViewer preview interactions stop");
                    this.innerWebsiteEditService.stop(this.content.el);
                }
            };
            onMounted(updatePreview);
            onPatched(updatePreview);

            onWillPatch(stopPreview);
            onWillUnmount(stopPreview);
        }
    },
});
