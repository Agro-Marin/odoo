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

                window.onYouTubeIframeAPIReady = () => resolve();
            } else {
                resolve();
            }
        });
    }

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

    async start() {
        if (!document.querySelector(`script[src="${this.vimeoScriptUrl}"]`)) {
            await this.host.waitFor(loadJS(this.vimeoScriptUrl));
        }
        await this._setupVideoPlayer();
    }

    async _setupVideoPlayer() {
        this.player = new Vimeo.Player(this.el.querySelector("iframe"));
        this.videoDuration = await this.host.waitFor(this.player.getDuration());
        this.player.on("timeupdate", this._onVideoTimeUpdate.bind(this));
        this.player.on("ended", this._onVideoEnded.bind(this));
    }

    _onVideoEnded() {
        if (this.slide.hasNext) {
            this.el.dispatchEvent(
                new CustomEvent("slide_go_next", { bubbles: true, detail: {} }),
            );
        }
    }

    /**
     * @param {Object} eventData
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

    goNext() {
        const currentIndex = this._getCurrentIndex();
        if (currentIndex < this.slideEntries.length - 1) {
            this._updateSlideEntry(this.slideEntries[currentIndex + 1]);
        }
    }

    goPrevious() {
        const currentIndex = this._getCurrentIndex();
        if (currentIndex >= 1) {
            this._updateSlideEntry(this.slideEntries[currentIndex - 1]);
        }
    }

    _getCurrentIndex() {
        const slide = this._slideEntry;
        return this.slideEntries.findIndex(
            (entry) => entry.id === slide.id && entry.isQuiz === slide.isQuiz,
        );
    }

    /**
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
        document.querySelector(".o_footer")?.classList.add("d-none");
        this._onChangeSlide();
    }

    _extractChannelData() {
        return this.el.dataset;
    }

    _getCurrentSlideID() {
        const activeItem = this.el.querySelector(
            ".o_wslides_fs_sidebar_list_item.active",
        );
        return parseInt(activeItem?.dataset.id);
    }

    _getSlides() {
        const slideList = [];
        for (const el of this.el.querySelectorAll(
            '.o_wslides_fs_sidebar_list_item[data-can-access="True"]',
        )) {
            slideList.push(parseSlideDataset(el.dataset));
        }
        return slideList;
    }

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

    _fetchSlideContent() {
        const slide = this._slideValue;
        if (slide.category === "article" && !slide.isQuiz) {
            return this._fetchHtmlContent();
        }
        return Promise.resolve();
    }

    _preprocessSlideData(slidesDataList) {
        slidesDataList.forEach(function (slideData, index) {
            slideData.hasNext = index < slidesDataList.length - 1;
            if (
                slideData.category === "video" &&
                slideData.videoSourceType !== "vimeo"
            ) {
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
            slideData.isQuiz = !!slideData.isQuiz;
            slideData.hasQuestion = !!slideData.hasQuestion;
            let autoSetDone = false;
            if (!slideData.hasQuestion) {
                if (
                    ["infographic", "document", "article"].includes(slideData.category)
                ) {
                    autoSetDone = true;
                } else if (
                    slideData.category === "video" &&
                    slideData.videoSourceType === "google_drive"
                ) {
                    autoSetDone = true;
                }
            }
            slideData._autoSetDone = autoSetDone;
        });
        return slidesDataList;
    }

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
     * @returns {Promise}
     */
    async _renderSlide() {
        if (this._renderSlideRunning) {
            return;
        }
        this._renderSlideRunning = true;
        try {
            const slide = this._slideValue;
            const content = this.el.querySelector(".o_wslides_fs_content");
            this.services["public.interactions"].stopInteractions(content);
            content.replaceChildren();

            if (slide.category === "quiz" || slide.isQuiz) {
                content.classList.add("bg-white");
                const { QuizBehavior } = await this.waitFor(
                    import("@website_slides/interactions/quiz"),
                );
                return await QuizBehavior.create(this, {
                    targetEl: content,
                    slideData: slide,
                    channelData: this.channel,
                });
            }

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

    _onChangeSlide() {
        const slide = this._slideValue;
        this._pushUrlState();
        return this._fetchSlideContent()
            .then(() => {
                const websiteName = document.title.split(" | ").at(-1);
                document.title = websiteName
                    ? slide.name + " | " + websiteName
                    : slide.name;
                if (uiUtils.getSize() < SIZES.MD) {
                    this._toggleSidebar();
                }
                return this._renderSlide();
            })
            .then(() => {
                if (slide._autoSetDone && !session.is_website_user) {
                    if (slide.category === "document") {
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
     * @override
     */
    async toggleSlideCompleted(slideData, completed = true) {
        await super.toggleSlideCompleted(...arguments);

        const fsSlides = this.slides.filter((_slide) => _slide.id === slideData.id);
        fsSlides.forEach((slide) => (slide.completed = completed));

        const currentSlide = this._slideValue;
        if (currentSlide.id === slideData.id) {
            currentSlide.completed = completed;
            if (
                (currentSlide.hasQuestion || currentSlide.type === "quiz") &&
                !completed
            ) {
                await this._renderSlide();
            }
        }
    }

    _onSlideGoToNext() {
        this.sidebar.goNext();
    }

    _onClickToggleSidebar() {
        this._toggleSidebar();
    }

    _onClickShareSlide() {
        const slide = this._slideValue;
        this.services.dialog.add(SlideShareDialog, {
            category: slide.category,
            documentMaxPage:
                slide.category === "document" ? getDocumentMaxPage() : undefined,
            emailSharing: slide.emailSharing,
            embedCode: slide.embedCode || "",
            id: slide.id,
            isFullscreen: true,
            name: slide.name,
            url: slide.websiteShareUrl,
        });
    }

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
