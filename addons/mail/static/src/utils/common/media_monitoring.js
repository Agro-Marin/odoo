/** @odoo-module native */
const HUMAN_VOICE_FREQUENCY_RANGE = [80, 1000];

/**
 * @typedef {Object} AudioMonitorOptions
 * @property {number[]} [frequencyRange]
 * @property {number} [minimumActiveCycles]
 * @property {(isAboveThreshold: boolean) => void} [onThreshold]
 * @property {(volume: number) => void} [onTic]
 * @property {number} [processInterval]
 * @property {number} [volumeThreshold]
 * @property {{boost: number, shift: number}} [normalizationParameters]
 */
/**
 * @typedef {Object} AudioMonitorProcessor
 * @property {() => void} disconnect
 */

/**
 * @param {MediaStreamTrack} track
 * @param {AudioMonitorOptions} [processorOptions]
 * @returns {Promise<() => Promise<void>>}
 */
export async function monitorAudio(track, processorOptions) {
    const monitoredTrack = track.clone();
    monitoredTrack.enabled = true;
    const stream = new window.MediaStream([monitoredTrack]);
    const AudioContext =
        window.AudioContext ||
        /** @type {{webkitAudioContext?: typeof globalThis.AudioContext}} */ (window)
            .webkitAudioContext;
    if (!AudioContext) {
        throw new Error("missing audio context");
    }
    const audioContext = new AudioContext();
    const source = audioContext.createMediaStreamSource(stream);

    let processor;
    try {
        processor = await _loadAudioWorkletProcessor(
            source,
            audioContext,
            processorOptions,
        );
    } catch {
        processor = _loadScriptProcessor(source, audioContext, processorOptions);
    }

    return async () => {
        processor.disconnect();
        source.disconnect();
        monitoredTrack.stop();
        try {
            await audioContext.close();
        } catch (e) {
            if (e.name === "InvalidStateError") {
                return;
            }
            throw e;
        }
    };
}

/**
 * @param {MediaStreamAudioSourceNode} source
 * @param {AudioContext} audioContext
 * @param {AudioMonitorOptions} [param2]
 * @returns {AudioMonitorProcessor}
 */
function _loadScriptProcessor(
    source,
    audioContext,
    {
        frequencyRange = HUMAN_VOICE_FREQUENCY_RANGE,
        minimumActiveCycles = 30,
        onThreshold,
        onTic,
        processInterval = 50,
        volumeThreshold = 0.3,
    } = {},
) {
    const bitSize = 1024;
    const analyser = audioContext.createAnalyser();
    source.connect(analyser);
    const scriptProcessorNode = audioContext.createScriptProcessor(bitSize, 1, 1);
    analyser.connect(scriptProcessorNode);
    analyser.fftSize = bitSize;
    scriptProcessorNode.connect(audioContext.destination);

    const intervalInFrames = (processInterval / 1000) * analyser.context.sampleRate;
    let nextUpdateFrame = intervalInFrames;

    let activityBuffer = 0;
    let wasAboveThreshold = undefined;
    let isAboveThreshold = false;

    scriptProcessorNode.onaudioprocess = () => {
        nextUpdateFrame -= bitSize;
        if (nextUpdateFrame >= 0) {
            return;
        }
        nextUpdateFrame += intervalInFrames;

        const normalizedVolume = getFrequencyAverage(
            analyser,
            frequencyRange[0],
            frequencyRange[1],
        );
        if (normalizedVolume >= volumeThreshold) {
            activityBuffer = minimumActiveCycles;
        } else if (normalizedVolume < volumeThreshold && activityBuffer > 0) {
            activityBuffer--;
        }
        isAboveThreshold = activityBuffer > 0;

        onTic?.(normalizedVolume);
        if (wasAboveThreshold !== isAboveThreshold) {
            wasAboveThreshold = isAboveThreshold;
            onThreshold?.(isAboveThreshold);
        }
    };
    return {
        disconnect: () => {
            analyser.disconnect();
            scriptProcessorNode.disconnect();
            scriptProcessorNode.onaudioprocess = null;
        },
    };
}

/**
 * @param {MediaStreamAudioSourceNode} source
 * @param {AudioContext} audioContext
 * @param {AudioMonitorOptions} [param2]
 * @returns {Promise<AudioMonitorProcessor>}
 */
async function _loadAudioWorkletProcessor(
    source,
    audioContext,
    {
        frequencyRange = HUMAN_VOICE_FREQUENCY_RANGE,
        minimumActiveCycles = 10,
        onThreshold,
        onTic,
        processInterval = 50,
        volumeThreshold = 0.3,
        normalizationParameters = { boost: 1, shift: 0.6 },
    } = {},
) {
    await audioContext.resume();
    await audioContext.audioWorklet.addModule("/mail/rtc/audio_worklet_processor_v2");
    const thresholdProcessor = new window.AudioWorkletNode(
        audioContext,
        "audio-processor",
        {
            processorOptions: {
                minimumActiveCycles,
                processInterval,
                volumeThreshold,
                frequencyRange,
                normalizationParameters,
                postAllTics: !!onTic,
            },
        },
    );
    source.connect(thresholdProcessor);
    thresholdProcessor.port.onmessage = /** @param {MessageEvent} event */ (event) => {
        const { isAboveThreshold, volume } = event.data;
        if (isAboveThreshold !== undefined) {
            onThreshold?.(isAboveThreshold);
        }
        if (volume !== undefined) {
            onTic?.(volume);
        }
    };
    return {
        disconnect: () => {
            thresholdProcessor.disconnect();
        },
    };
}

/**
 * @param {AnalyserNode & {_freqBuffer?: Uint8Array}} analyser
 * @param {number} lowerFrequency
 * @param {number} higherFrequency
 * @returns {number}
 */
function getFrequencyAverage(analyser, lowerFrequency, higherFrequency) {
    const frequencies = (analyser._freqBuffer ??= new window.Uint8Array(
        analyser.frequencyBinCount,
    ));
    analyser.getByteFrequencyData(frequencies);
    const sampleRate = analyser.context.sampleRate;
    const startIndex = _getFrequencyIndex(
        lowerFrequency,
        sampleRate,
        analyser.frequencyBinCount,
    );
    const endIndex = _getFrequencyIndex(
        higherFrequency,
        sampleRate,
        analyser.frequencyBinCount,
    );
    const count = endIndex - startIndex;
    let sum = 0;
    for (let index = startIndex; index < endIndex; index++) {
        sum += frequencies[index] / 255;
    }
    if (!count) {
        return 0;
    }
    return sum / count;
}

/**
 * @param {number} targetFrequency
 * @param {number} sampleRate
 * @param {number} binCount
 * @returns {number}
 */
function _getFrequencyIndex(targetFrequency, sampleRate, binCount) {
    const index = Math.round((targetFrequency / (sampleRate / 2)) * binCount);
    return Math.min(Math.max(0, index), binCount);
}
