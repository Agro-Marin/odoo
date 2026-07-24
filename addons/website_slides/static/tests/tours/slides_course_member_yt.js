import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";

let fullScreenPatched = false;
function patchFullScreen() {
    /**
     * Alter this method for test purposes.
     * This will make the video start at 10 minutes.
     * As it lasts 10min24s, it will mark it as completed immediately.
     *
     * The FullscreenPlayer class is fetched from the module loader (the
     * already-loaded frontend instance) rather than a static import: this
     * test file lives in a separate asset bundle, and statically importing
     * the interaction would re-evaluate its module there, re-registering it
     * in `public.interactions` with a second `Interaction` identity (the
     * registry schema predicate then transiently rejects it).
     */
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

/**
 * Global use case:
 * an user (either employee, website restricted editor or portal) joins a public
    course;
 * they have access to the full course content when they are a member of the
    course;
 * they use fullscreen player to complete the course;
 * they rate the course;
 */
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
        // eLearning: go on /all, find free course and join it
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
            // check membership
            trigger: '.o_wslides_js_course_join:contains("You\'re enrolled")',
        },
        {
            trigger: 'a:contains("Comparing Hardness of Wood Species")',
            run: "click",
        },
        {
            // check progression
            trigger: '.o_wslides_progress_percentage:contains("50")',
        },
        {
            trigger: '.o_wslides_fs_slide_name:contains("Wood Bending With Steam Box")',
            run: "click",
        },
        {
            // check player loading
            trigger: ".player",
        },
        {
            // check that video slide is marked as 'done'
            trigger:
                '.o_wslides_fs_sidebar_section_slides li:contains("Wood Bending With Steam Box") .o_wslides_slide_completed',
        },
        {
            // check progression
            trigger: ".o_wslides_channel_completion_completed:contains(Completed)",
        },
        {
            trigger: 'a:contains("Back to course")',
            run: "click",
        },
    ],
});
