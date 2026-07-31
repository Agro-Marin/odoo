
interface Element {
    querySelector<E extends HTMLElement = HTMLElement>(
        selectors: string
    ): E | null;

    querySelectorAll<E extends HTMLElement = HTMLElement>(
        selectors: string
    ): NodeListOf<E>;
}

interface MediaSettingsRange {
    max: number;
    min: number;
    step: number;
}

interface MediaTrackCapabilities {
    zoom?: MediaSettingsRange;
}

interface MediaTrackSettings {
    zoom?: number;
}

interface MediaTrackConstraintSet {
    zoom?: ConstrainDouble;
}
