/** @odoo-module native */
import { AutoComplete } from "@web/components/autocomplete/autocomplete";

/**
 * AutoComplete variant that can broaden a country-scoped partner search to a
 * worldwide one. The "Search Worldwide" entry is a real, keyboard-navigable
 * option (see PartnerAutoCompleteCore.worldwideOption) rather than a template
 * add-on, so it participates in navigation, aria state and Enter-to-select.
 */
export class PartnerAutoComplete extends AutoComplete {
  setup() {
    super.setup();
    this.shouldSearchWorldwide = false;
  }

  // Thread the worldwide flag to the (function) source loaders. The generic
  // AutoComplete calls `options(request)`; partner sources read the 2nd arg.
  loadOptions(options, request) {
    if (typeof options === "function") {
      return options(request, this.shouldSearchWorldwide);
    }
    return options;
  }

  // The worldwide entry carries no onSelect (its behaviour lives in
  // selectOption below), so force it selectable or navigate()/Enter skip it.
  makeOption(option) {
    const made = super.makeOption(option);
    if (made.data?.isWorldwideAction) {
      made.unselectable = false;
    }
    return made;
  }

  selectOption(option) {
    if (option?.data?.isWorldwideAction) {
      this.searchWorldwide();
      return;
    }
    super.selectOption(option);
  }

  searchWorldwide() {
    this.shouldSearchWorldwide = true;
    // Reopen so the sources reload with the worldwide scope. close()+open()
    // (not cancel()) keeps the flag we just set.
    this.close();
    this.open(true);
  }

  // A genuine new keystroke starts a fresh, country-scoped search: the
  // worldwide affordance is re-offered instead of staying latched on.
  onInput() {
    this.shouldSearchWorldwide = false;
    return super.onInput();
  }

  cancel() {
    this.shouldSearchWorldwide = false;
    super.cancel();
  }
}
