import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";

let fullScreenPatched = false;
function patchFullScreen() {
    if (fullScreenPatched) {
        return;
    }
    fullScreenPatched = true;
    const { FullscreenPlayer } = odoo.loader.modules.get(
        "@website_slides/interactions/fullscreen_player",
    );
    patch(FullscreenPlayer.prototype, {
        _renderSlide() {
            const slide = this._slideValue;
            slide.embedUrl += "&start=260";
            this._updateSlideValue(slide);

            return super._renderSlide(...arguments);
        },
    });
}

registry.category("web_tour.tours").add("course_member_youtube", {
    url: "/slides",
    steps: () => [
        {
            content: "Patching FullScreen",
            trigger: "body",
            run: function () {
                patchFullScreen();
            },
        },
        {
            trigger: "a.o_wslides_home_all_slides",
            run: "click",
        },
        {
            trigger: 'a:contains("Choose your wood")',
            run: "click",
        },
        {
            trigger: 'a:contains("Join this Course")',
            run: "click",
        },
        {
            trigger: '.o_wslides_js_course_join:contains("You\'re enrolled")',
        },
        {
            trigger: 'a:contains("Comparing Hardness of Wood Species")',
            run: "click",
        },
        {
            trigger: '.o_wslides_progress_percentage:contains("50")',
        },
        {
            trigger: '.o_wslides_fs_slide_name:contains("Wood Bending With Steam Box")',
            run: "click",
        },
        {
            trigger: ".player",
        },
        {
            trigger:
                '.o_wslides_fs_sidebar_section_slides li:contains("Wood Bending With Steam Box") .o_wslides_slide_completed',
        },
        {
            trigger: ".o_wslides_channel_completion_completed:contains(Completed)",
        },
        {
            trigger: 'a:contains("Back to course")',
            run: "click",
        },
    ],
});
