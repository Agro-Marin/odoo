/** @odoo-module native */
import { rpc } from "@web/core/network";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { renderToElement } from "@web/core/utils/render";
import { Popover } from "@web/libs/bootstrap";
import { Interaction } from "@web/public/interaction";

/**
 * "Join this course" behavior, shared between:
 * - the course page join links (attached to server-rendered DOM by the
 *   `CourseJoin` interaction below);
 * - the quiz and fullscreen player, which render the "slide.course.join"
 *   template themselves (see `attachCourseJoin`).
 *
 * It is a plain class driven by a host Interaction (listener registration
 * goes through the host so cleanup follows the host's lifecycle). Downstream
 * modules customize it with `patch(CourseJoinBehavior.prototype, ...)`
 * (e.g. website_sale_slides adds the "on payment" enroll flow).
 */
export class CourseJoinBehavior {
    /**
     * @param {import("@web/public/interaction").Interaction} host
     * @param {HTMLElement} el the element containing the join link
     * @param {Object} options
     * @param {Object} options.channel slide.channel information
     * @param {boolean} options.isMember whether current user is enrolled
     * @param {boolean} options.isMemberOrInvited whether current user is at least invited
     * @param {string} options.inviteHash hash of the invited attendee. Needed to grant
     *   access to a course preview / to identify.
     * @param {integer} options.invitePartnerId id of partner of invited attendee if any.
     *   Also needed to access course preview / to identify.
     * @param {boolean} options.invitePreview whether the course is rendered as a preview.
     *   This is true when an invited attendee is on the course while unlogged.
     * @param {boolean} options.isPartnerWithoutUser whether invited partner has users. Used
     *   to redirect properly to sign up / log in.
     * @param {boolean} options.publicUser whether the current user is public (unlogged)
     * @param {string} [options.joinMessage] the message to use for the simple join case
     *   when the course is free and the user is logged in, defaults to "Join this Course".
     * @param {Function} [options.beforeJoin] a promise-returning function to execute before
     *   we redirect to another url within the join process (login / buy course / ...)
     * @param {Function} [options.afterJoin] a callback function called after the user has
     *   joined the course
     */
    constructor(host, el, options) {
        this.host = host;
        this.el = el;
        this.channel = options.channel;
        this.isMember = options.isMember;
        this.isMemberOrInvited = options.isMemberOrInvited;
        this.inviteHash = options.inviteHash;
        this.invitePartnerId = options.invitePartnerId;
        this.invitePreview = options.invitePreview;
        this.isPartnerWithoutUser = options.isPartnerWithoutUser;
        this.publicUser = options.publicUser;
        this.joinMessage = options.joinMessage || _t("Join this Course");
        this.beforeJoin =
            options.beforeJoin ||
            function () {
                return Promise.resolve();
            };
        this.afterJoin =
            options.afterJoin ||
            function () {
                document.location.reload();
            };
        this.setup(options);
        host.addListener(el, "click", (ev) => {
            if (ev.target.closest(".o_wslides_js_course_join_link")) {
                this._onClickJoin(ev);
            }
        });
    }

    /**
     * Extension hook for downstream modules (patched prototypes cannot wrap
     * the constructor itself).
     *
     * @param {Object} options the constructor options, after assignment
     */
    setup(options) {}

    //--------------------------------------------------------------------------
    // Handlers
    //--------------------------------------------------------------------------

    /**
     * @param {MouseEvent} ev
     */
    _onClickJoin(ev) {
        ev.preventDefault();

        if (
            this.invitePreview ||
            (this.channel.channelEnroll === "invite" && this.isMemberOrInvited)
        ) {
            this.joinChannel(this.channel.channelId);
            return;
        }

        if (this.channel.channelEnroll !== "invite") {
            if (this.publicUser) {
                this.beforeJoin().then(this._redirectToLogin.bind(this));
            } else if (!this.isMember) {
                this.joinChannel(this.channel.channelId);
            }
        }
    }

    //--------------------------------------------------------------------------
    // Private
    //--------------------------------------------------------------------------

    /**
     * Builds a login page that then redirects to this slide page, or the
     * channel if the course is not configured as public enroll type.
     */
    _redirectToLogin() {
        let url;
        if (this.channel.channelEnroll === "public") {
            url = window.location.pathname;
            if (document.location.href.indexOf("fullscreen") !== -1) {
                url += "?fullscreen=1";
            }
        } else {
            url = `/slides/${encodeURIComponent(this.channel.channelId)}`;
        }
        document.location = `/web/login?redirect=${encodeURIComponent(url)}`;
    }

    /**
     * Shows a Bootstrap 5 popover alert on the given element.
     *
     * @param {HTMLElement} el
     * @param {String|HTMLElement} message
     */
    _popoverAlert(el, message) {
        const popover = new Popover(el, {
            trigger: "focus",
            delay: { hide: 300 },
            placement: "bottom",
            container: "body",
            html: true,
            content: function () {
                return message;
            },
        });
        popover.show();
    }

    //--------------------------------------------------------------------------
    // Public
    //--------------------------------------------------------------------------

    /**
     * @param {integer} channelId
     */
    async joinChannel(channelId) {
        const data = await this.host.waitFor(
            rpc("/slides/channel/join", { channel_id: channelId }),
        );
        if (!data.error) {
            this.afterJoin();
        } else if (data.error === "public_user") {
            const popupContent = renderToElement("slide.course.join.popupContent", {
                channelId: channelId,
                courseUrl: encodeURIComponent(document.URL),
                errorSignupAllowed: data.error_signup_allowed,
                widget: this,
            });
            this._popoverAlert(this.el, popupContent);
        } else if (data.error === "join_done") {
            this._popoverAlert(this.el, _t("You have already joined this channel"));
        } else {
            this._popoverAlert(this.el, _t("Unknown error"));
        }
    }
}

/**
 * Renders the "slide.course.join" join button inside `targetEl` and attaches
 * the join behavior to it. Used by the quiz and the fullscreen player.
 *
 * @param {import("@web/public/interaction").Interaction} host
 * @param {HTMLElement} targetEl
 * @param {Object} options see {@link CourseJoinBehavior}
 * @returns {CourseJoinBehavior}
 */
export function attachCourseJoin(host, targetEl, options) {
    // The template reads its values through the historical `widget` context
    // key; it only uses these three fields.
    const [el] = host.renderAt(
        "slide.course.join",
        {
            widget: {
                channel: options.channel,
                joinMessage: options.joinMessage || _t("Join this Course"),
                isMemberOrInvited: options.isMemberOrInvited,
            },
        },
        targetEl,
    );
    return new CourseJoinBehavior(host, el, options);
}

/**
 * Attaches the join behavior to the server-rendered join areas of the course
 * page. Options are read from the join link's dataset, as before.
 */
export class CourseJoin extends Interaction {
    static selector = ".o_wslides_js_course_join_link";

    start() {
        const data = this.el.dataset;
        const options = {
            channel: {
                channelEnroll: data.channelEnroll,
                // dataset values are strings; the join endpoint browses this id
                channelId: parseInt(data.channelId),
            },
            inviteHash: data.inviteHash,
            invitePartnerId: data.invitePartnerId,
            invitePreview: data.invitePreview,
            isMemberOrInvited: data.isMemberOrInvited,
            isPartnerWithoutUser: data.isPartnerWithoutUser,
        };
        for (const el of document.querySelectorAll(".o_wslides_js_course_join")) {
            new CourseJoinBehavior(this, el, options);
        }
    }
}

registry.category("public.interactions").add("website_slides.course_join", CourseJoin);
