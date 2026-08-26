/** @odoo-module native */
/* global YT, Vimeo */

import { markup } from "@odoo/owl";
import { loadJS } from "@web/core/assets";
import { rpc } from "@web/core/network";
import { registry } from "@web/core/registry";
import { renderToElement } from "@web/core/utils/render";
import { session } from "@web/session";
import { SIZES, utils as uiUtils } from "@web/ui/viewport";
import { unhideConditionalElements } from "@website/utils/misc";
import { CoursePage } from "@website_slides/interactions/course_page";
import {
    findSlide,
    getDocumentMaxPage,
    parseSlideBoolean,
    parseSlideDataset,
} from "@website_slides/js/public/slides_course_utils";

import { SlideShareDialog } from "../js/public/components/slide_share_dialog/slide_share_dialog.js";

/**
 * Renders and drives the YouTube player for a video slide.
 *
 * Dispatches a bubbling `slide_mark_completed` event when the player is at
 * 30 sec before the end of the video (30 sec before is considered as
 * completed), and `slide_go_next` when the video is at its end.
 */
export class VideoPlayerYouTube {
    youtubeUrl = "https://www.youtube.com/iframe_api";

    constructor(host, slide, targetEl) {
        this.host = host;
        this.slide = slide;
        [this.el] = host.renderAt(
            "website.slides.fullscreen.video.youtube",
            { widget: this },
            targetEl,
        );
    }

    async start() {
        await this.host.waitFor(this._loadYoutubeAPI());
        this._setupYoutubePlayer();
    }

    _loadYoutubeAPI() {
        return new Promise((resolve) => {
            if (!document.querySelector(`script[src="${this.youtubeUrl}"]`)) {
                const script = document.createElement("script");
                script.src = this.youtubeUrl;
                document.head.appendChild(script);

                // function called when the Youtube asset is loaded
                // see https://developers.google.com/youtube/iframe_api_reference#Requirements
                window.onYouTubeIframeAPIReady = () => resolve();
            } else {
                resolve();
            }
        });
    }

    /**
     * Links the youtube api to the iframe present in the template.
     */
    _setupYoutubePlayer() {
        this.player = new YT.Player("youtube-player" + this.slide.id, {
            playerVars: {
                autoplay: 1,
                origin: window.location.origin,
            },
            events: {
                onStateChange: this._onPlayerStateChange.bind(this),
            },
        });
        this.host.registerCleanup(() => {
            if (this.tid) {
                clearInterval(this.tid);
            }
        });
    }

    /**
     * Specific method of the youtube api.
     * Whenever the player starts playing/pausing/buffering/..., a setinterval
     * is created. This setinterval is used to check the user's progress in the
     * video. Once the user reaches a particular time in the video (30s before
     * end), the slide will be considered as completed if the video doesn't
     * have a mini-quiz. This method also allows to automatically go to the
     * next slide (or the quiz associated to the current video) once the video
     * is over.
     *
     * @param {*} event
     */
    _onPlayerStateChange(event) {
        if (this.slide.completed) {
            return;
        }

        if (event.data !== YT.PlayerState.ENDED) {
            if (!event.target.getCurrentTime) {
                return;
            }

            if (this.tid) {
                clearInterval(this.tid);
            }

            this.currentVideoTime = event.target.getCurrentTime();
            this.totalVideoTime = event.target.getDuration();
            this.tid = setInterval(() => {
                this.currentVideoTime += 1;
                if (
                    this.totalVideoTime &&
                    this.currentVideoTime > this.totalVideoTime - 30
                ) {
                    clearInterval(this.tid);
                    if (
                        this.slide.isMember &&
                        !this.slide.hasQuestion &&
                        !this.slide.completed
                    ) {
                        this.el.dispatchEvent(
                            new CustomEvent("slide_mark_completed", {
                                bubbles: true,
                                detail: this.slide,
                            }),
                        );
                    }
                }
            }, 1000);
        } else {
            if (this.tid) {
                clearInterval(this.tid);
            }
            this.player = undefined;
            if (this.slide.hasNext) {
                this.el.dispatchEvent(
                    new CustomEvent("slide_go_next", { bubbles: true, detail: {} }),
                );
            }
        }
    }
}

/**
 * Renders and drives the Vimeo player for a video slide.
 *
 * Similarly to the YouTube implementation, dispatches `slide_mark_completed`
 * when the player is at 30 sec before the end of the video, and
 * `slide_go_next` when the video is at its end.
 *
 * See https://developer.vimeo.com/player/sdk/reference for the API doc.
 */
export class VideoPlayerVimeo {
    vimeoScriptUrl = "https://player.vimeo.com/api/player.js";

    constructor(host, slide, targetEl) {
        this.host = host;
        this.slide = slide;
        [this.el] = host.renderAt(
            "website.slides.fullscreen.video.vimeo",
            { widget: this },
            targetEl,
        );
    }

    /**
     * Loads the Vimeo JS API (only if not already loaded), then instantiates
     * the player.
     */
    async start() {
        if (!document.querySelector(`script[src="${this.vimeoScriptUrl}"]`)) {
            await this.host.waitFor(loadJS(this.vimeoScriptUrl));
        }
        await this._setupVideoPlayer();
    }

    /**
     * Instantiate the Vimeo player and register the various events.
     */
    async _setupVideoPlayer() {
        this.player = new Vimeo.Player(this.el.querySelector("iframe"));
        this.videoDuration = await this.host.waitFor(this.player.getDuration());
        this.player.on("timeupdate", this._onVideoTimeUpdate.bind(this));
        this.player.on("ended", this._onVideoEnded.bind(this));
    }

    /**
     * When the player triggers the 'ended' event, we go to the next slide if
     * there is one.
     */
    _onVideoEnded() {
        if (this.slide.hasNext) {
            this.el.dispatchEvent(
                new CustomEvent("slide_go_next", { bubbles: true, detail: {} }),
            );
        }
    }

    /**
     * Every time the video changes position, Vimeo triggers this 'timeupdate'
     * event. We use it to set the slide as completed as soon as we reach the
     * end (30 last seconds).
     *
     * @param {Object} eventData the 'timeupdate' event data
     */
    _onVideoTimeUpdate(eventData) {
        if (eventData.seconds > this.videoDuration - 30) {
            if (
                this.slide.isMember &&
                !this.slide.hasQuestion &&
                !this.slide.completed
            ) {
                this.el.dispatchEvent(
                    new CustomEvent("slide_mark_completed", {
                        bubbles: true,
                        detail: this.slide,
                    }),
                );
            }
        }
    }
}

/**
 * Sidebar navigation from one slide to another:
 *  - by clicking on any slide list entry
 *  - by keyboard arrows (left / right)
 *  - by receiving the order to go to prev/next slide (`goPrevious` and
 *    `goNext` public methods)
 *
 * Calls the `onChangeSlide` callback with the new slide entry.
 */
export class SidebarBehavior {
    constructor(host, el, slideList, defaultSlide, onChangeSlide) {
        this.host = host;
        this.el = el;
        this.slideEntries = slideList;
        this._slideEntry = defaultSlide;
        this.onChangeSlide = onChangeSlide;

        host.addListener(el, "click", (ev) => {
            const target = ev.target.closest(
                ".o_wslides_fs_sidebar_list_item .o_wslides_fs_slide_name",
            );
            if (target && el.contains(target)) {
                this._onClickTab(ev, target);
            }
        });
        host.addListener(document, "keydown", this._onKeyDown.bind(this));
    }

    //--------------------------------------------------------------------------
    // Public
    //--------------------------------------------------------------------------

    /**
     * Change the current slide with the next one (if there is one).
     */
    goNext() {
        const currentIndex = this._getCurrentIndex();
        if (currentIndex < this.slideEntries.length - 1) {
            this._updateSlideEntry(this.slideEntries[currentIndex + 1]);
        }
    }

    /**
     * Change the current slide with the previous one (if there is one).
     */
    goPrevious() {
        const currentIndex = this._getCurrentIndex();
        if (currentIndex >= 1) {
            this._updateSlideEntry(this.slideEntries[currentIndex - 1]);
        }
    }

    //--------------------------------------------------------------------------
    // Private
    //--------------------------------------------------------------------------

    /**
     * Get the index of the current slide entry (slide and/or quiz)
     */
    _getCurrentIndex() {
        const slide = this._slideEntry;
        return this.slideEntries.findIndex(
            (entry) => entry.id === slide.id && entry.isQuiz === slide.isQuiz,
        );
    }

    //--------------------------------------------------------------------------
    // Handlers
    //--------------------------------------------------------------------------

    /**
     * Handler called when the user clicks on a normal slide tab.
     *
     * @param {Event} ev
     * @param {HTMLElement} target
     */
    _onClickTab(ev, target) {
        ev.stopPropagation();
        const elem = target.closest(".o_wslides_fs_sidebar_list_item");
        if (parseSlideBoolean(elem.dataset.canAccess)) {
            const isQuiz = parseSlideBoolean(elem.dataset.isQuiz);
            const slideID = Number(elem.dataset.id);
            const slide = findSlide(this.slideEntries, { id: slideID, isQuiz: isQuiz });
            this._updateSlideEntry(slide);
        }
    }

    /**
     * Actively changes the active tab in the sidebar so that it corresponds
     * to the slide currently displayed.
     *
     * @param {Object} slide
     */
    _updateSlideEntry(slide) {
        if (this._slideEntry === slide) {
            return;
        }
        this._slideEntry = slide;
        const active = this.el.querySelector(".o_wslides_fs_sidebar_list_item.active");
        if (active) {
            active.classList.remove("active");
        }
        const selector =
            '.o_wslides_fs_sidebar_list_item[data-id="' +
            slide.id +
            '"]:not([data-is-quiz="1"])';
        const newActive = this.el.querySelector(selector);
        if (newActive) {
            newActive.classList.add("active");
        }
        this.onChangeSlide(this._slideEntry);
    }

    /**
     * Binds left and right arrow to allow the user to navigate between slides.
     *
     * @param {KeyboardEvent} ev
     */
    _onKeyDown(ev) {
        switch (ev.key) {
            case "ArrowLeft":
                this.goPrevious();
                break;
            case "ArrowRight":
                this.goNext();
                break;
        }
    }
}

/**
 * Shows the content of a course, navigating through contents and correctly
 * displaying them. Also handles slide completion, course progress, ...
 *
 * The page skeleton (sidebar included) is rendered server side; the slide
 * content area is rendered client side on each slide change.
 */
export class FullscreenPlayer extends CoursePage {
    static selector = ".o_wslides_fs_main";

    dynamicContent = {
        ...this.dynamicContent,
        ".o_wslides_fs_toggle_sidebar": {
            "t-on-click.prevent": this._onClickToggleSidebar,
        },
        ".o_wslides_fs_share": { "t-on-click": this._onClickShareSlide },
        _root: {
            ...this.dynamicContent._root,
            "t-on-slide_go_next": this._onSlideGoToNext,
        },
    };

    start() {
        this.initialSlideID = this._getCurrentSlideID();
        this.slides = this._preprocessSlideData(this._getSlides());
        this.channel = this._extractChannelData();
        let slide;
        const urlParams = new URL(window.location).searchParams;
        if (this.initialSlideID) {
            slide = findSlide(this.slides, {
                id: this.initialSlideID,
                isQuiz: String(urlParams.get("quiz")) === "1",
            });
        } else {
            slide = this.slides[0];
        }
        this._slideValue = slide;

        this.sidebar = new SidebarBehavior(
            this,
            this.el.querySelector(".o_wslides_fs_sidebar"),
            this.slides,
            slide,
            (slideEntry) => this._onChangeSlideRequest(slideEntry),
        );

        this._toggleSidebar();
        const backendNavEl = document.querySelector(".o_frontend_to_backend_nav");
        if (backendNavEl) {
            backendNavEl.remove();
        }
        // To prevent double scrollbar due to footer overflow
        document.querySelector(".o_footer")?.classList.add("d-none");
        // trigger manually once DOM ready, since slide content is not rendered server side
        this._onChangeSlide();
    }

    //--------------------------------------------------------------------------
    // Private
    //--------------------------------------------------------------------------

    _extractChannelData() {
        return this.el.dataset;
    }

    _getCurrentSlideID() {
        const activeItem = this.el.querySelector(
            ".o_wslides_fs_sidebar_list_item.active",
        );
        return parseInt(activeItem?.dataset.id);
    }

    /**
     * Creates slides objects from every slide-list-cells attributes.
     */
    _getSlides() {
        const slideList = [];
        for (const el of this.el.querySelectorAll(
            '.o_wslides_fs_sidebar_list_item[data-can-access="True"]',
        )) {
            slideList.push(parseSlideDataset(el.dataset));
        }
        return slideList;
    }

    /**
     * Fetches content with an rpc call for slides of category "article".
     */
    _fetchHtmlContent() {
        const currentSlide = this._slideValue;
        return this.waitFor(
            rpc("/slides/slide/get_html_content", { slide_id: currentSlide.id }),
        ).then(function (data) {
            if (data.html_content) {
                currentSlide.htmlContent = data.html_content;
            }
        });
    }

    /**
     * Fetches slide content depending on its category.
     * If the slide doesn't need to fetch any content, return a resolved
     * promise.
     */
    _fetchSlideContent() {
        const slide = this._slideValue;
        if (slide.category === "article" && !slide.isQuiz) {
            return this._fetchHtmlContent();
        }
        return Promise.resolve();
    }

    /**
     * Extend the slide data list to add informations about rendering method,
     * and other specific values according to their slide_category.
     */
    _preprocessSlideData(slidesDataList) {
        slidesDataList.forEach(function (slideData, index) {
            // compute hasNext slide
            slideData.hasNext = index < slidesDataList.length - 1;
            // compute embed url
            if (
                slideData.category === "video" &&
                slideData.videoSourceType !== "vimeo"
            ) {
                // embedCode contains an iframe tag, where src attribute is the url (youtube or embed document from odoo)
                const tmp = document.createElement("div");
                tmp.innerHTML = slideData.embedCode;
                const iframe = tmp.querySelector("iframe");
                slideData.embedCode = iframe?.getAttribute("src") || "";
                const separator = slideData.embedCode.indexOf("?") !== -1 ? "&" : "?";
                const scheme = slideData.embedCode.indexOf("//") === 0 ? "https:" : "";
                const params = {
                    rel: 0,
                    enablejsapi: 1,
                    origin: window.location.origin,
                };
                if (slideData.embedCode.indexOf("//drive.google.com") === -1) {
                    params.autoplay = 1;
                }
                slideData.embedUrl = slideData.embedCode
                    ? scheme +
                      slideData.embedCode +
                      separator +
                      new URLSearchParams(params).toString()
                    : "";
            } else if (
                slideData.category === "video" &&
                slideData.videoSourceType === "vimeo"
            ) {
                slideData.embedCode = markup(slideData.embedCode);
            } else if (slideData.category === "infographic") {
                slideData.embedUrl = `/web/image/slide.slide/${encodeURIComponent(slideData.id)}/image_1024`;
            } else if (slideData.category === "document") {
                const tmp = document.createElement("div");
                tmp.innerHTML = slideData.embedCode;
                const iframe = tmp.querySelector("iframe");
                slideData.embedUrl = iframe?.getAttribute("src");
            }
            // fill empty property to allow searching on it with list.filter(matcher)
            slideData.isQuiz = !!slideData.isQuiz;
            slideData.hasQuestion = !!slideData.hasQuestion;
            // technical settings for the Fullscreen to work
            let autoSetDone = false;
            if (!slideData.hasQuestion) {
                if (
                    ["infographic", "document", "article"].includes(slideData.category)
                ) {
                    autoSetDone = true; // images, documents (local + external) and articles are marked as completed when opened
                } else if (
                    slideData.category === "video" &&
                    slideData.videoSourceType === "google_drive"
                ) {
                    autoSetDone = true; // google drive videos do not benefit from the YouTube integration and are marked as completed when opened
                }
            }
            slideData._autoSetDone = autoSetDone;
        });
        return slidesDataList;
    }

    /**
     * Changes the url whenever the user changes slides.
     * This allows the user to refresh the page and stay on the right slide.
     */
    _pushUrlState() {
        const urlParts = window.location.pathname.split("/");
        urlParts[urlParts.length - 1] = this._slideValue.slug;
        const url = urlParts.join("/");
        const exitLink = this.el.querySelector(".o_wslides_fs_exit_fullscreen");
        if (exitLink) {
            exitLink.setAttribute("href", url);
        }
        const params = { fullscreen: 1 };
        if (this._slideValue.isQuiz) {
            params.quiz = 1;
        }
        const fullscreenUrl = `${url}?${new URLSearchParams(params).toString()}`;
        history.pushState(null, "", fullscreenUrl);
    }

    /**
     * Render the current slide content using specific mechanism according to
     * slide category:
     * - simply append content (for article)
     * - template rendering (for image, document, ....)
     * - using a sub behavior (quiz and video)
     *
     * @returns {Promise}
     */
    async _renderSlide() {
        // Avoid concurrent execution of the slide rendering as it writes the content at the same place anyway.
        if (this._renderSlideRunning) {
            return;
        }
        this._renderSlideRunning = true;
        try {
            const slide = this._slideValue;
            const content = this.el.querySelector(".o_wslides_fs_content");
            // Stop before replacing, not only start after: `startInteractions`
            // refuses to start an interaction already active on an element, and
            // `.o_wslides_fs_content` matches interactions itself (TextHighlight
            // does) -- so one started on the empty container at page load stayed
            // registered and the slide body rendered here never got its turn.
            // That is why a saved `.o_text_highlight` reached fullscreen with no
            // SVG. It also drops whatever the previous slide's body had started.
            this.services["public.interactions"].stopInteractions(content);
            content.replaceChildren();

            // display quiz slide, or quiz attached to a slide
            if (slide.category === "quiz" || slide.isQuiz) {
                content.classList.add("bg-white");
                // Lazy import: the quiz module (and its course_join dependency)
                // is only needed for quiz slides, and importing it eagerly
                // pulls the whole chain into the fullscreen module's eager
                // eval position, which reorders public.interactions
                // registrations under the tour test bundle.
                const { QuizBehavior } = await this.waitFor(
                    import("@website_slides/interactions/quiz"),
                );
                return await QuizBehavior.create(this, {
                    targetEl: content,
                    slideData: slide,
                    channelData: this.channel,
                });
            }

            // render slide content
            if (["document", "infographic"].includes(slide.category)) {
                content.replaceChildren(
                    renderToElement("website.slides.fullscreen.content", {
                        widget: this,
                    }),
                );
            } else if (
                slide.category === "video" &&
                slide.videoSourceType === "youtube"
            ) {
                this.videoPlayer = new VideoPlayerYouTube(this, slide, content);
                return await this.videoPlayer.start();
            } else if (
                slide.category === "video" &&
                slide.videoSourceType === "vimeo"
            ) {
                this.videoPlayer = new VideoPlayerVimeo(this, slide, content);
                return await this.videoPlayer.start();
            } else if (
                slide.category === "video" &&
                slide.videoSourceType === "google_drive"
            ) {
                content.replaceChildren(
                    renderToElement("website.slides.fullscreen.video.google_drive", {
                        widget: this,
                    }),
                );
            } else if (slide.category === "article") {
                const wpContainer = document.createElement("div");
                wpContainer.className =
                    "o_wslide_fs_article_content bg-white block w-100 overflow-auto p-3";
                wpContainer.innerHTML = slide.htmlContent;
                content.appendChild(wpContainer);
                this.services["public.interactions"].startInteractions(content);
            }
            unhideConditionalElements();
        } finally {
            this._renderSlideRunning = false;
        }
    }

    _updateSlideValue(slide) {
        if (this._slideValue === slide) {
            return;
        }
        this._slideValue = slide;
        this._onChangeSlide();
    }

    //--------------------------------------------------------------------------
    // Handlers
    //--------------------------------------------------------------------------

    /**
     * Triggered whenever the user changes slides.
     * When the current slide is changed, the player will be automatically
     * updated and allowed to: fetch the content if needed, render it, update
     * the url, and set slide as "completed" according to its category
     * requirements. In mobile case (i.e. limited screensize), sidebar will be
     * toggled since sidebar will block most or all of new slide visibility.
     */
    _onChangeSlide() {
        const slide = this._slideValue;
        this._pushUrlState();
        return this._fetchSlideContent()
            .then(() => {
                // render content
                const websiteName = document.title.split(" | ").at(-1); // get the website name from title
                document.title = websiteName
                    ? slide.name + " | " + websiteName
                    : slide.name;
                if (uiUtils.getSize() < SIZES.MD) {
                    this._toggleSidebar(); // hide sidebar when small device screen
                }
                return this._renderSlide();
            })
            .then(() => {
                if (slide._autoSetDone && !session.is_website_user) {
                    // no useless RPC call
                    if (slide.category === "document") {
                        // only set the slide as completed after iFrame is loaded to avoid concurrent execution with 'embedUrl' controller
                        this.el
                            .querySelector("iframe.o_wslides_iframe_viewer")
                            .addEventListener("load", () =>
                                this.toggleSlideCompleted(slide),
                            );
                    } else {
                        return this.toggleSlideCompleted(slide);
                    }
                }
            });
    }

    /**
     * Changes current slide when the sidebar reports a slide change, with its
     * id and whether it is its quiz we need to display.
     *
     * @param {Object} slideData
     */
    _onChangeSlideRequest(slideData) {
        const newSlide = findSlide(this.slides, {
            id: slideData.id,
            isQuiz: slideData.isQuiz || false,
        });
        this._updateSlideValue(newSlide);
    }

    /**
     * After a slide has been marked as completed / uncompleted, update the
     * state of this player and reload the slide if needed (e.g. to re-show
     * the questions of a quiz).
     *
     * We might need to set multiple slides as completed, because of "isQuiz"
     * set to True / False.
     *
     * @override
     */
    async toggleSlideCompleted(slideData, completed = true) {
        await super.toggleSlideCompleted(...arguments);

        const fsSlides = this.slides.filter((_slide) => _slide.id === slideData.id);
        fsSlides.forEach((slide) => (slide.completed = completed));

        const currentSlide = this._slideValue;
        if (currentSlide.id === slideData.id) {
            currentSlide.completed = completed;
            // `_updateSlideValue(currentSlide)` used to sit here; it opens with
            // `if (this._slideValue === slide) return`, and currentSlide *is*
            // this._slideValue, so it was an unconditional no-op. Removed
            // rather than repaired: the re-render below is the only thing it
            // could have wanted, and it already happens.
            if (
                (currentSlide.hasQuestion || currentSlide.type === "quiz") &&
                !completed
            ) {
                // Reload the quiz
                await this._renderSlide();
            }
        }
    }

    /**
     * Go to the next slide.
     */
    _onSlideGoToNext() {
        this.sidebar.goNext();
    }

    /**
     * Called when the sidebar toggle is clicked -> toggles the sidebar
     * visibility.
     */
    _onClickToggleSidebar() {
        this._toggleSidebar();
    }

    _onClickShareSlide() {
        const slide = this._slideValue;
        this.services.dialog.add(SlideShareDialog, {
            category: slide.category,
            documentMaxPage: slide.category === "document" && getDocumentMaxPage(),
            // `slide` came from parseSlideDataset, so this is already a real
            // boolean. Comparing it to the string "True" -- as share.js
            // correctly does on the *raw* dataset -- was false every time, so
            // the email-sharing input never rendered in fullscreen.
            emailSharing: slide.emailSharing,
            embedCode: slide.embedCode || "",
            id: slide.id,
            isFullscreen: true,
            name: slide.name,
            url: slide.websiteShareUrl,
        });
    }

    /**
     * Toggles sidebar visibility.
     */
    _toggleSidebar() {
        this.el
            .querySelector(".o_wslides_fs_sidebar")
            .classList.toggle("o_wslides_fs_sidebar_hidden");
        this.el
            .querySelector(".o_wslides_fs_toggle_sidebar")
            .classList.toggle("active");
    }
}

registry
    .category("public.interactions")
    .add("website_slides.fullscreen_player", FullscreenPlayer);
