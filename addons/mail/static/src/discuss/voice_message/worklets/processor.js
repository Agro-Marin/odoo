/** @odoo-module native */
class AudioProcessor extends AudioWorkletProcessor {
    /** @param {AudioWorkletNodeOptions} [options] */
    constructor(options) {
        super();
    }
    /**
     * @param {Float32Array[][]} allInputs
     * @returns {boolean}
     */
    process(allInputs) {
        const inputs = allInputs[0][0];
        this.port.postMessage(inputs);
        return true;
    }
}
registerProcessor("processor", AudioProcessor);
