/** @odoo-module native */
import { Component, onMounted, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";

export class SlideXPProgressBar extends Component {
    static props = {
        previousRank: Object,
        newRank: Object,
        levelUp: Boolean,
    };
    static template = "website_slides.SlideXPProgressBar";

    setup() {
        super.setup();
        this.state = useState({
            hideRankBounds: true,
            rankLowerBound: this.props.previousRank.lower_bound,
            rankProgressPercentage: this.props.previousRank.progress,
            userKarma: this.props.previousRank.karma,
            rankUpperBound: this.props.previousRank.upper_bound,
        });
        onMounted(() => {
            this.animateProgressBar();
        });
    }

    /**
     * @public
     */
    animateProgressBar() {
        const duration = this.props.levelUp ? 1700 : 800;
        const startTime = Date.now();

        const animateKarma = () => {
            const progress = (Date.now() - startTime) / duration;
            if (progress >= 1) {
                this.state.userKarma = this.props.newRank.karma;
            } else {
                this.state.userKarma = Math.ceil(
                    this.props.previousRank.karma +
                        (this.props.newRank.karma - this.props.previousRank.karma) *
                            progress,
                );
                browser.requestAnimationFrame(animateKarma);
            }
        };

        this.state.hideRankBounds = false;
        browser.requestAnimationFrame(animateKarma);
        this.state.rankProgressPercentage = this.props.newRank.progress;

        if (this.props.levelUp) {
            browser.setTimeout(() => {
                this.state.rankLowerBound = this.props.newRank.lower_bound;
                this.state.rankUpperBound = this.props.newRank.upper_bound;
            }, 800);
        }
    }
}
