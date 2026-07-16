/** @odoo-module native */
/**
 * Provides a way to start JS code for snippets' initialization and animations.
 */
import publicWidget from "@web/legacy/js/public/public_widget";

/**
 * Add the notion of edit mode to public widgets.
 */
publicWidget.Widget.include({
    /**
     * Indicates if the widget should not be instantiated in edit. The default
     * is true, indeed most (all?) defined widgets only want to initialize
     * events and states which should not be active in edit mode (this is
     * especially true for non-website widgets).
     *
     * @type {boolean}
     */
    disabledInEditableMode: true,
    /**
     * Acts as @see Widget.events except that the events are only binded if the
     * Widget instance is instanciated in edit mode. The property is not
     * considered if @see disabledInEditableMode is false.
     */
    edit_events: null,
    /**
     * Acts as @see Widget.events except that the events are only binded if the
     * Widget instance is instanciated in readonly mode. The property only
     * makes sense if @see disabledInEditableMode is false, you should simply
     * use @see Widget.events otherwise.
     */
    read_events: null,

    /**
     * Initializes the events that will need to be binded according to the
     * given mode.
     *
     * @constructor
     * @param {Object} parent
     * @param {Object} [options]
     * @param {boolean} [options.editableMode=false]
     *        true if the page is in edition mode
     */
    init: function (parent, options) {
        this._super.apply(this, arguments);

        this.editableMode = this.options.editableMode || false;
        const extraEvents = this.editableMode ? this.edit_events : this.read_events;
        if (extraEvents) {
            this.events = Object.assign({}, this.events || {}, extraEvents);
        }
    },
});

//::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::

const registry = publicWidget.registry;

// NOTE: A legacy patch of ``window.SelectorEngine.find`` used to live here to
// swallow rare errors during edit-mode carousel cycling.  It was removed with
// the migration to Bootstrap's native ESM bundle — ``SelectorEngine`` is now
// a module-scoped binding inside ``bootstrap.esm.js`` and is no longer exposed
// on ``window``, so the monkey-patch cannot take effect.  If the edit-mode
// carousel crash resurfaces, patch ``Carousel.prototype`` at the public API
// level (see ``@web/libs/bootstrap``) instead of touching internals.

export default {
    Widget: publicWidget.Widget,
    registry: registry,
};
