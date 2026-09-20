import { TurnStile } from "@website_cf_turnstile/interactions/turnstile";

export function patchTurnStile() {
    TurnStile.turnstileURL = "";
}
