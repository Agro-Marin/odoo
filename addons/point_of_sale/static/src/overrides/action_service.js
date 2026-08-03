/** @odoo-module native */
import { patch } from "@web/core/utils/patch";
import { ActionManager } from "@web/webclient/actions";

// The PoS UI has no main action container, so an action targeting it is simply
// never shown. Route it to a dialog instead.
//
// On the manager's prototype, not on the object `start` returns: that object is
// an ActionManager instance and its API lives on the prototype, so wrapping it
// by spreading (`{...superReturn, doAction}`) produced a plain object carrying
// `doAction` and nothing else -- `doActionButton`, `switchView`, `restore`,
// `loadState` and the `currentController`/`currentAction` accessors all came
// out undefined. Pressing any button on a form the PoS opens (Edit Partner,
// Order Details) died on `doActionButton is not a function`.
patch(ActionManager.prototype, {
    doAction(actionRequest, options = {}) {
        if (
            document.body.classList.contains("modal-open") &&
            typeof actionRequest === "object"
        ) {
            actionRequest.target = "new";
        }
        return super.doAction(actionRequest, options);
    },
});
