/** The bundled encoder attaches these constructors when lamejs() initializes. */
declare namespace lamejs {
    class Mp3Encoder {
        constructor(channels: number, sampleRate: number, bitRate: number);
        encodeBuffer(left: Int16Array, right?: Int16Array): Int8Array;
        flush(): Int8Array;
    }
}
