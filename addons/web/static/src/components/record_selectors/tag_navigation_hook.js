// @ts-check
/** @odoo-module native */

/** @module @web/components/record_selectors/tag_navigation_hook - Keyboard navigation hook for moving between and deleting tags in record selectors */

import { useRef } from "@odoo/owl";
import { useNavigation } from "@web/services/navigation/navigation";
/**
 * Navigate between tags in a record selector with arrow keys and delete them
 * with backspace. Used in components containing both `Autocomplete` and `TagList`.
 *
 * @param {string} refName Name of the t-ref which contains the `Autocomplete` and `TagList` components.
 * @param {object} [options]
 * @param {() => boolean} [options.isEnabled]
 * @param {(index: number) => void} [options.delete] Function to be called when a tag is deleted. It should take the index of the tag to delete as parameter.
 */
export function useTagNavigation(refName, options = {}) {
    const tagsContainerRef = useRef(refName);

    const isEnabled = options.isEnabled ?? (() => true);

    const canRemoveTag = (target) =>
        options.delete && (target.tagName.toLowerCase() !== "input" || !target.value);

    const onBackspaceKeydown = (navigator) => {
        const el = navigator.activeItem.el;
        // Tag indices are computed relative to the actual tag items rather
        // than assuming the input is the last navigable item, so a template
        // reordering can't silently delete the wrong tag.
        const tagItems = navigator.items.filter((item) =>
            item.el.classList.contains("o_tag"),
        );
        if (el.classList.contains("o-autocomplete--input")) {
            if (!el.value && tagItems.length) {
                options.delete(tagItems.length - 1);
            }
        } else {
            options.delete(tagItems.indexOf(navigator.activeItem));
        }
        const inputItem = navigator.items.find((item) =>
            item.el.classList.contains("o-autocomplete--input"),
        );
        (inputItem ?? navigator.items.at(-1)).setActive();
    };

    const canNavigateFromInput = (navigator, navNext) => {
        const el = navigator.activeItem.el;
        if (el.classList.contains("o-autocomplete--input")) {
            const menu = tagsContainerRef.el.querySelector(
                ".o-autocomplete--dropdown-menu",
            );
            const index = navNext ? el.value.length : 0;
            if (el.selectionStart !== index || menu) {
                return false;
            }
        }
        return true;
    };

    useNavigation(tagsContainerRef, {
        getItems: () => [
            ...(tagsContainerRef.el?.querySelectorAll(
                ":scope .o_tag, :scope .o-autocomplete--input",
            ) ?? []),
        ],
        isNavigationAvailable: ({ navigator, target }) =>
            isEnabled() && navigator.isFocused && navigator.contains(target),
        hotkeys: {
            tab: null,
            "shift+tab": null,
            home: null,
            end: null,
            enter: null,
            arrowup: null,
            arrowdown: null,
            backspace: {
                bypassEditableProtection: true,
                isAvailable: ({ target }) => canRemoveTag(target),
                callback: (navigator) => onBackspaceKeydown(navigator),
            },
            arrowleft: {
                bypassEditableProtection: true,
                isAvailable: ({ navigator }) => canNavigateFromInput(navigator, false),
                callback: (navigator) => navigator.previous(),
            },
            arrowright: {
                bypassEditableProtection: true,
                isAvailable: ({ navigator }) => canNavigateFromInput(navigator, true),
                callback: (navigator) => navigator.next(),
            },
        },
    });
}
