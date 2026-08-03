// @ts-check
/** @odoo-module native */

/** @module @web/components/barcode/crop_overlay */

import { Component, useEffect, useRef } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { isIOS } from "@web/core/browser/feature_detection";
import { clamp } from "@web/core/utils/format/numbers";

const AREA_KEYS = ["x", "y", "width", "height"];

export class CropOverlay extends Component {
    static template = "web.CropOverlay";
    static props = {
        onResize: Function,
        isReady: Boolean,
        slots: {
            type: Object,
            shape: {
                default: {},
            },
        },
    };

    setup() {
        this.localStorageKey = "o-barcode-scanner-overlay";
        this.cropContainerRef = useRef("crop-container");
        this.isMoving = false;
        this.boundaryOverlay = {};
        this.relativePosition = {
            x: 0,
            y: 0,
        };
        this.hasInitialPosition = false;
        /** @type {{x: number, y: number, width: number, height: number} | null} */
        this.notifiedArea = null;
        useEffect(
            (el, isReady) => {
                if (!el || !isReady) {
                    this.hasInitialPosition = false;
                    return;
                }
                this.setupCropRect();
                const observer = new ResizeObserver(() => this.setupCropRect());
                observer.observe(el);
                return () => observer.disconnect();
            },
            () => [this.cropContainerRef.el, this.props.isReady],
        );
        this.isIOS = isIOS();
    }

    setupCropRect() {
        if (!this.props.isReady || !this.cropContainerRef.el) {
            return;
        }
        if (!this.hasInitialPosition) {
            this.computeDefaultPoint();
            this.hasInitialPosition = true;
        }
        this.computeOverlayPosition();
        this.calculateAndSetTransparentRect();
        this.notifyResize();
    }

    boundPoint(pointValue, boundaryRect) {
        return {
            x: clamp(
                pointValue.x,
                boundaryRect.left,
                boundaryRect.left + boundaryRect.width,
            ),
            y: clamp(
                pointValue.y,
                boundaryRect.top,
                boundaryRect.top + boundaryRect.height,
            ),
        };
    }

    calculateAndSetTransparentRect() {
        const cropTransparentRect = this.getTransparentRec(
            this.relativePosition,
            this.boundaryOverlay,
        );
        this.setCropValue(cropTransparentRect, this.relativePosition);
    }

    computeOverlayPosition() {
        const cropOverlayElement =
            this.cropContainerRef.el.querySelector(".o_crop_overlay");
        this.boundaryOverlay = cropOverlayElement.getBoundingClientRect();
    }

    notifyResize() {
        const transparentRec = this.getTransparentRec(
            this.relativePosition,
            this.boundaryOverlay,
        );
        const area = {
            ...transparentRec,
            width: this.boundaryOverlay.width - 2 * transparentRec.x,
            height: this.boundaryOverlay.height - 2 * transparentRec.y,
        };
        if (
            this.notifiedArea &&
            AREA_KEYS.every((key) => this.notifiedArea[key] === area[key])
        ) {
            return;
        }
        this.notifiedArea = area;
        this.props.onResize(area);
    }

    /**
     * What is stored is the handle's own position, because that is what
     * `computeDefaultPoint` reads it back into. Storing the transparent rect
     * instead put the two in different coordinate spaces: the rect is the
     * handle mirrored about the centre, and mirroring is idempotent, so the
     * crop area came back right while the handle came back on the opposite
     * corner. A value written by the previous spelling is already a mirrored
     * point, which restores to the same area it always did.
     */
    persistPosition() {
        browser.localStorage.setItem(
            this.localStorageKey,
            JSON.stringify(this.relativePosition),
        );
    }

    computeDefaultPoint() {
        const firstChildComputedStyle = getComputedStyle(
            /** @type {Element} */ (this.cropContainerRef.el.firstChild),
        );
        const elementWidth = parseFloat(firstChildComputedStyle.width);
        const elementHeight = parseFloat(firstChildComputedStyle.height);

        const stringSavedPoint = browser.localStorage.getItem(this.localStorageKey);
        let savedPoint;
        if (stringSavedPoint) {
            try {
                savedPoint = JSON.parse(stringSavedPoint);
            } catch {
                browser.localStorage.removeItem(this.localStorageKey);
            }
        }
        if (typeof savedPoint?.x === "number" && typeof savedPoint?.y === "number") {
            this.relativePosition = {
                x: clamp(savedPoint.x, 0, elementWidth),
                y: clamp(savedPoint.y, 0, elementHeight),
            };
        } else {
            const stepWidth = elementWidth / 10;
            const width = stepWidth * 8;
            const height = width / 4;
            const startY = elementHeight / 2 - height / 2;
            this.relativePosition = {
                x: stepWidth + width,
                y: startY + height,
            };
        }
    }
    getTransparentRec(point, rect) {
        const middleX = rect.width / 2;
        const middleY = rect.height / 2;
        const newDeltaX = Math.abs(point.x - middleX);
        const newDeltaY = Math.abs(point.y - middleY);
        return {
            x: middleX - newDeltaX,
            y: middleY - newDeltaY,
        };
    }

    setCropValue(point, iconPoint) {
        if (!iconPoint) {
            iconPoint = point;
        }
        this.cropContainerRef.el.style.setProperty("--o-crop-x", `${point.x}px`);
        this.cropContainerRef.el.style.setProperty("--o-crop-y", `${point.y}px`);
        this.cropContainerRef.el.style.setProperty(
            "--o-crop-icon-x",
            `${iconPoint.x}px`,
        );
        this.cropContainerRef.el.style.setProperty(
            "--o-crop-icon-y",
            `${iconPoint.y}px`,
        );
    }

    pointerDown(event) {
        if (event.target.matches("input")) {
            return;
        }
        event.preventDefault();
        if (event.target.matches(".o_crop_icon")) {
            this.computeOverlayPosition();
            this.isMoving = true;
            try {
                event.currentTarget.setPointerCapture(event.pointerId);
            } catch {}
        }
    }

    pointerMove(event) {
        if (!this.isMoving) {
            return;
        }
        const { clientX, clientY } = event;
        const restrictedPosition = this.boundPoint(
            {
                x: clientX,
                y: clientY,
            },
            this.boundaryOverlay,
        );
        this.relativePosition = {
            x: restrictedPosition.x - this.boundaryOverlay.left,
            y: restrictedPosition.y - this.boundaryOverlay.top,
        };
        this.calculateAndSetTransparentRect();
    }

    pointerUp(event) {
        if (!this.isMoving) {
            return;
        }
        this.isMoving = false;
        this.persistPosition();
        this.notifyResize();
    }
}
