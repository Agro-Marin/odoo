/** @odoo-module native */
import { rpc } from "@web/core/network";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { renderToElement } from "@web/core/utils/render";
import { Popover } from "@web/libs/bootstrap";
import { Interaction } from "@web/public/interaction";

export class CourseJoinBehavior {
    /**
     * @param {import("@web/public/interaction").Interaction} host
     * @param {HTMLElement} el
     * @param {Object} options
     * @param {Object} options.channel
     * @param {boolean} options.isMember
     * @param {boolean} options.isMemberOrInvited
     * @param {string} options.inviteHash
     * @param {integer} options.invitePartnerId
     * @param {boolean} options.invitePreview
     * @param {boolean} options.isPartnerWithoutUser
     * @param {boolean} options.publicUser
     * @param {string} [options.joinMessage]
     * @param {Function} [options.beforeJoin]
     * @param {Function} [options.afterJoin]
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
     * @param {Object} options
     */
    setup(options) {}

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
 * @param {import("@web/public/interaction").Interaction} host
 * @param {HTMLElement} targetEl
 * @param {Object} options
 * @returns {CourseJoinBehavior}
 */
export function attachCourseJoin(host, targetEl, options) {
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

export class CourseJoin extends Interaction {
    static selector = ".o_wslides_js_course_join_link";

    start() {
        const data = this.el.dataset;
        const options = {
            channel: {
                channelEnroll: data.channelEnroll,
                channelId: parseInt(data.channelId),
            },
            inviteHash: data.inviteHash,
            invitePartnerId: data.invitePartnerId,
            invitePreview: data.invitePreview,
            isMemberOrInvited: data.isMemberOrInvited,
            isPartnerWithoutUser: data.isPartnerWithoutUser,
        };
        const wrapperEl = this.el.closest(".o_wslides_js_course_join");
        if (wrapperEl) {
            new CourseJoinBehavior(this, wrapperEl, options);
        }
    }
}

registry.category("public.interactions").add("website_slides.course_join", CourseJoin);
