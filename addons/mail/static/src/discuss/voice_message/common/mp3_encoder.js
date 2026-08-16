/** @odoo-module native */
const MAX_SAMPLES = 1152;

export class Mp3Encoder {
    /** @type {Object} */
    config;
    /** @type {boolean} */
    encoding;
    /** @type {lameJs.Mp3Encoder} */
    mp3Encoder;
    /** @type {Int16Array} */
    samplesMono;

    /**
     * @param {Object} [config={}]
     * @param {number} [config.sampleRate=44100]
     * @param {number} [config.bitRate=128]
     */
    constructor(config = {}) {
        this.config = {
            sampleRate: 44100,
            bitRate: 128,
        };
        Object.assign(this.config, config);
        // eslint-disable-next-line no-undef
        this.mp3Encoder = new lamejs.Mp3Encoder(
            1,
            this.config.sampleRate,
            this.config.bitRate,
        );
        this.samplesMono = null;
        this.clearBuffer();
    }

    clearBuffer() {
        this.dataBuffer = [];
    }

    /** @param {ArrayBuffer|Int8Array} buffer */
    appendToBuffer(buffer) {
        this.dataBuffer.push(new Int8Array(buffer));
    }

    /**
     * @param {Float32Array} input
     * @param {Int16Array} output
     */
    floatTo16BitPCM(input, output) {
        for (let i = 0; i < input.length; i++) {
            const s = Math.max(-1, Math.min(1, input[i]));
            output[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }
    }

    /**
     * @param {Float32Array} arrayBuffer
     * @returns {Int16Array}
     */
    convertBuffer(arrayBuffer) {
        const data = new Float32Array(arrayBuffer);
        const out = new Int16Array(arrayBuffer.length);
        this.floatTo16BitPCM(data, out);
        return out;
    }

    /** @param {Float32Array} arrayBuffer */
    encode(arrayBuffer) {
        this.encoding = true;
        this.samplesMono = this.convertBuffer(arrayBuffer);
        let remaining = this.samplesMono.length;
        for (let i = 0; remaining > 0; i += MAX_SAMPLES) {
            const left = this.samplesMono.subarray(i, i + MAX_SAMPLES);
            const mp3buffer = this.mp3Encoder.encodeBuffer(left);
            this.appendToBuffer(mp3buffer);
            remaining -= MAX_SAMPLES;
        }
    }

    finish() {
        if (this.encoding) {
            this.appendToBuffer(this.mp3Encoder.flush());
            return this.dataBuffer;
        } else {
            return [];
        }
    }
}
