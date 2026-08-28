/** @odoo-module native */
import { Message } from "@mail/core/common/message";
import { onWillUnmount } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";

const ELEMENT_NODE = 1;
const TEXT_NODE = 3;

/**
 * @param {Element|CharacterData} el
 * @param {string} selector
 * @returns {Element|undefined}
 */
function previousMatching(el, selector) {
    let sibling = el.previousElementSibling;
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
    if (!condition) {
        hide(el);
        return;
    }
    let newDisplay = el.dataset.oMailDisplay;
    if (newDisplay === "none") {
        newDisplay = null;
    }
    el.style.display = newDisplay;
}

/** @param {ChildNode} childEl */
function isRendered(childEl) {
    return (
        childEl.nodeType === ELEMENT_NODE ||
        (childEl.nodeType === TEXT_NODE && childEl.nodeValue.trim())
    );
}

/**
 * A text node after the "stop spelling" marker belongs to the quote, but only
 * an element can carry the data attribute the grouping reads, so it is wrapped.
 * @param {Element|CharacterData} childEl
 * @returns {Element|CharacterData}
 */
function quoteTextNode(childEl) {
    if (
        childEl.nodeType !== TEXT_NODE ||
        !previousMatching(childEl, '[id*="stopSpelling"]')
    ) {
        return childEl;
    }
    const newChildEl = document.createElement("span");
    newChildEl.textContent = childEl.textContent;
    newChildEl.dataset.oMailQuote = "1";
    childEl.parentNode.replaceChild(newChildEl, childEl);
    return newChildEl;
}

/** @param {Element|CharacterData} childEl */
function isQuoted(childEl) {
    return Boolean(
        (childEl.nodeType === ELEMENT_NODE &&
            /** @type {Element} */ (childEl).getAttribute("data-o-mail-quote")) ||
        (childEl.nodeName === "BR" &&
            previousMatching(childEl, '[data-o-mail-quote="1"]')),
    );
}

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

    /**
     * Hides every run of quoted nodes in bodyEl and returns those runs, so each
     * can be given its own ellipsis button. Recurses into anything unquoted.
     * @param {HTMLElement} bodyEl
     * @returns {(Element|CharacterData)[][]}
     */
    collectQuoteGroups(bodyEl) {
        const groups = [];
        /** @type {(Element|CharacterData)[]|undefined} */
        let ellipsisNodes;
        const childrenEl = /** @type {(Element|CharacterData)[]} */ (
            Array.from(bodyEl.childNodes).filter(isRendered)
        );
        for (const childEl of childrenEl) {
            const nodeEl = quoteTextNode(childEl);
            if (!isQuoted(nodeEl)) {
                ellipsisNodes = undefined;
                this.insertEllipsisbtn(/** @type {HTMLElement} */ (nodeEl));
                continue;
            }
            if (!ellipsisNodes) {
                ellipsisNodes = [];
                groups.push(ellipsisNodes);
            }
            hide(/** @type {HTMLElement} */ (nodeEl));
            ellipsisNodes.push(nodeEl);
        }
        return groups;
    },

    /** @param {(Element|CharacterData)[]} group */
    insertEllipsisbtnForGroup(group) {
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
    },

    /** @param {HTMLElement} bodyEl */
    insertEllipsisbtn(bodyEl) {
        for (const group of this.collectQuoteGroups(bodyEl)) {
            this.insertEllipsisbtnForGroup(group);
        }
    },
};
patch(Message.prototype, messagePatch);
