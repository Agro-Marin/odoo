/** @odoo-module native */
import { rpc } from "@web/core/network";
import { renderToElement } from "@web/core/utils/render";
import { Interaction } from "@web/public/interaction";
import { session } from "@web/session";

/**
 * Abstract base for both the fullscreen view and non-fullscreen view of a
 * slide course (NOT registered). Contains general methods to update the UI
 * elements (progress bar, sidebar...) as well as methods to mark a slide as
 * completed / uncompleted.
 *
 * Descendants of the course page (join button, quiz, ...) communicate
 * completion through bubbling DOM CustomEvents carrying their payload in
 * `detail` (`slide_completed`, `slide_mark_completed`) — the Interaction
 * replacement for the legacy widget `trigger_up` flows.
 */
export class CoursePage extends Interaction {
    dynamicContent = {
        "button.o_wslides_button_complete": {
            "t-on-click.stop.prevent": this.onClickComplete,
        },
        _root: {
            "t-on-slide_completed": (ev) => this.onSlideCompleted(ev.detail),
            "t-on-slide_mark_completed": (ev) => this.onSlideMarkCompleted(ev.detail),
        },
    };

    /**
     * Collapse the next category when the current one has just been completed.
     *
     * @param {Integer} nextCategoryId
     */
    collapseNextCategory(nextCategoryId) {
        const categorySectionEl = document.getElementById(
            `category-collapse-${nextCategoryId}`,
        );
        if (categorySectionEl?.getAttribute("aria-expanded") === "false") {
            categorySectionEl.setAttribute("aria-expanded", true);
            document
                .querySelector(`ul[id=collapse-${nextCategoryId}]`)
                .classList.add("show");
        }
    }

    /**
     * Greens up the bullet when the slide is completed.
     *
     * @param {Object} slideData
     * @param {Boolean} completed
     */
    toggleCompletionButton(slideData, completed = true) {
        const buttonEl = this.el.querySelector(
            `.o_wslides_sidebar_done_button[data-id="${slideData.id}"]`,
        );

        if (!buttonEl) {
            return;
        }

        const newButtonEl = renderToElement("website.slides.sidebar.done.button", {
            slideId: slideData.id,
            uncompletedIcon: buttonEl.dataset.uncompletedIcon ?? "fa-regular fa-circle",
            slideCompleted: completed ? 1 : 0,
            canSelfMarkUncompleted: slideData.canSelfMarkUncompleted,
            canSelfMarkCompleted: slideData.canSelfMarkCompleted,
            isMember: slideData.isMember,
        });
        buttonEl.replaceWith(newButtonEl);
    }

    /**
     * Updates the progressbar whenever a lesson is completed.
     *
     * @param {Integer} channelCompletion
     */
    updateProgressbar(channelCompletion) {
        const completion = Math.min(100, channelCompletion);
        const isCompleted = completion === 100;

        for (const el of document.querySelectorAll(
            ".o_wslides_channel_completion_completed",
        )) {
            el.classList.toggle("d-none", !isCompleted);
        }
        for (const el of document.querySelectorAll(
            ".o_wslides_channel_completion_progressbar",
        )) {
            el.classList.toggle("d-none", isCompleted);
            el.classList.toggle("d-flex", !isCompleted);
            const progressBarEl = el.querySelector(".progress-bar");
            if (progressBarEl) {
                progressBarEl.style.width = `${completion}%`;
            }
            const percentageEl = el.querySelector(".o_wslides_progress_percentage");
            if (percentageEl) {
                percentageEl.textContent = completion;
            }
        }
    }

    /**
     * Once the completion conditions are filled, rpc call to set the relation
     * between the slide and the user as "completed".
     *
     * @param {Object} slideData slide to set as completed
     * @param {Boolean} completed true to mark the slide as completed,
     *     false to mark the slide as not completed
     */
    async toggleSlideCompleted(slideData, completed = true) {
        if (
            !!slideData.completed === !!completed ||
            !slideData.isMember ||
            !slideData.canSelfMarkCompleted
        ) {
            // no useless RPC call
            return;
        }
        const data = await this.waitFor(
            rpc(`/slides/slide/${completed ? "set_completed" : "set_uncompleted"}`, {
                slide_id: slideData.id,
            }),
        );
        this.toggleCompletionButton(slideData, completed);
        this.updateProgressbar(data.channel_completion);
        if (data.next_category_id) {
            this.collapseNextCategory(data.next_category_id);
        }
    }

    /**
     * Retrieve the slide data corresponding to the slide id given in argument.
     * The data comes from the "slide_sidebar_done_button" template dataset.
     *
     * @param {Integer} slideId
     * @returns {DOMStringMap|undefined}
     */
    getSlide(slideId) {
        const el = document.querySelector(
            `.o_wslides_sidebar_done_button[data-id="${slideId}"]`,
        );
        return el ? el.dataset : undefined;
    }

    /**
     * We clicked on the "done" button: RPC call to update the slide state,
     * then update the UI.
     *
     * @param {MouseEvent} ev
     */
    onClickComplete(ev) {
        const buttonEl = ev.currentTarget.closest(".o_wslides_sidebar_done_button");
        const slideData = buttonEl.dataset;
        const isCompleted = Boolean(parseInt(slideData.completed));
        this.toggleSlideCompleted(slideData, !isCompleted);
    }

    /**
     * The slide has been completed, update the UI.
     *
     * @param {Object} detail `slide_completed` event payload
     * @param {Integer} detail.slideId
     * @param {Boolean} detail.completed
     * @param {Integer} detail.channelCompletion
     */
    onSlideCompleted({ slideId, completed, channelCompletion }) {
        const slideData = this.getSlide(slideId);
        if (slideData) {
            // Just joined the course (e.g. When "Submit & Join" action), update the UI
            this.toggleCompletionButton(slideData, completed);
        }
        this.updateProgressbar(channelCompletion);
    }

    /**
     * Make a RPC call to complete the slide then update the UI.
     *
     * @param {Object} detail `slide_mark_completed` event payload
     * @param {Integer} detail.id the slide id
     */
    onSlideMarkCompleted(detail) {
        if (!session.is_website_user) {
            // no useless RPC call
            const slideData = this.getSlide(detail.id);
            this.toggleSlideCompleted(slideData, true);
        }
    }
}
