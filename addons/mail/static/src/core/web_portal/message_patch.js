/** @odoo-module native */
import { Message } from "@mail/core/common/message";
import { onWillUnmount } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";

/**
 * @typedef {Message & { state: Message["state"] & { lastReadMoreIndex: number, isReadMoreByIndex: Map<number, boolean>, }, }} MessageWithReadMore
 */
/** @type {Partial<MessageWithReadMore> & ThisType<MessageWithReadMore>} */
const messagePatch = {
    setup() {
        super.setup(...arguments);
        this.state.lastReadMoreIndex = 0;
        this.state.isReadMoreByIndex = new Map();
        onWillUnmount(() => {
            this.messageBody.el?.querySelector(".o-mail-ellipsis")?.remove();
        });
    },

    /** @param {HTMLElement} bodyEl */
    prepareMessageBody(bodyEl) {
        if (!bodyEl) {
            return;
        }
        super.prepareMessageBody(...arguments);
        Array.from(bodyEl.querySelectorAll(".o-mail-ellipsis")).forEach((el) =>
            el.remove(),
        );
        this.state.lastReadMoreIndex = 0;
        this.insertEllipsisbtn(bodyEl);
    },

    /** @param {HTMLElement} bodyEl */
    insertEllipsisbtn(bodyEl) {
        /**
         * @param {Element|CharacterData} e
         * @param {string} selector
         * @returns {Element[]}
         */
        function prevAll(e, selector) {
            const res = [];
            let sibling = e.previousElementSibling;
            while (sibling) {
                if (sibling.matches(selector)) {
                    res.push(sibling);
                }
                sibling = sibling.previousElementSibling;
            }
            return res;
        }

        /**
         * @param {Element|CharacterData} e
         * @param {string} selector
         * @returns {Element|undefined}
         */
        function prev(e, selector) {
            let sibling = e.previousElementSibling;
            while (sibling) {
                if (sibling.matches(selector)) {
                    return sibling;
                }
                sibling = sibling.previousElementSibling;
            }
        }

        /** @param {HTMLElement} el */
        function hide(el) {
            el.dataset.oMailDisplay = el.style.display;
            el.style.display = "none";
        }

        /**
         * @param {HTMLElement} el
         * @param {boolean} condition
         */
        function toggle(el, condition = false) {
            if (condition) {
                let newDisplay = el.dataset.oMailDisplay;
                if (newDisplay === "none") {
                    newDisplay = null;
                }
                el.style.display = newDisplay;
            } else {
                hide(el);
            }
        }

        const groups = [];
        /** @type {(Element|CharacterData)[]|undefined} */
        let ellipsisNodes;
        const ELEMENT_NODE = 1;
        const TEXT_NODE = 3;
        /**
         * @type {(Element|CharacterData)[]}
         */
        const childrenEl = /** @type {(Element|CharacterData)[]} */ (
            Array.from(bodyEl.childNodes).filter(
                /** @param {ChildNode} childEl */
                function (childEl) {
                    return (
                        childEl.nodeType === ELEMENT_NODE ||
                        (childEl.nodeType === TEXT_NODE && childEl.nodeValue.trim())
                    );
                },
            )
        );
        for (const childEl of childrenEl) {
            if (
                childEl.nodeType === TEXT_NODE &&
                prevAll(childEl, '[id*="stopSpelling"]').length > 0
            ) {
                const newChildEl = document.createElement("span");
                newChildEl.textContent = childEl.textContent;
                newChildEl.dataset.oMailQuote = "1";
                childEl.parentNode.replaceChild(newChildEl, childEl);
            }
            if (
                (childEl.nodeType === ELEMENT_NODE &&
                    /** @type {Element} */ (childEl).getAttribute(
                        "data-o-mail-quote",
                    )) ||
                (childEl.nodeName === "BR" && prev(childEl, '[data-o-mail-quote="1"]'))
            ) {
                if (!ellipsisNodes) {
                    ellipsisNodes = [];
                    groups.push(ellipsisNodes);
                }
                hide(/** @type {HTMLElement} */ (childEl));
                ellipsisNodes.push(childEl);
            } else {
                ellipsisNodes = undefined;
                this.insertEllipsisbtn(/** @type {HTMLElement} */ (childEl));
            }
        }

        for (const group of groups) {
            const index = this.state.lastReadMoreIndex++;
            const ellipsisbtnEl = document.createElement("button");
            ellipsisbtnEl.className =
                "o-mail-ellipsis badge rounded-pill border-0 py-0 px-1";
            const iconellipsisEl = document.createElement("i");
            iconellipsisEl.className = "oi oi-ellipsis-h oi-large";
            ellipsisbtnEl.append(iconellipsisEl);
            group[0].parentNode.insertBefore(ellipsisbtnEl, group[0]);
            if (!this.state.isReadMoreByIndex.has(index)) {
                this.state.isReadMoreByIndex.set(index, true);
            }
            const updateFromState = () => {
                const isReadMore = this.state.isReadMoreByIndex.get(index);
                for (const childEl of group) {
                    hide(/** @type {HTMLElement} */ (childEl));
                    toggle(/** @type {HTMLElement} */ (childEl), !isReadMore);
                }
            };
            ellipsisbtnEl.addEventListener(
                "click",
                /** @param {MouseEvent} e */ (e) => {
                    e.preventDefault();
                    this.state.isReadMoreByIndex.set(
                        index,
                        !this.state.isReadMoreByIndex.get(index),
                    );
                    updateFromState();
                },
            );
            updateFromState();
        }
    },
};
patch(Message.prototype, messagePatch);
