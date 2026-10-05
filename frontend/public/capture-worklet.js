/* AudioWorklet captures native-rate mono float samples. Not MediaRecorder. */
class CaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Float32Array(2048);
    this.offset = 0;
  }
  process(inputs) {
    const channels = inputs[0];
    if (!channels || !channels.length) return true;
    for (let i = 0; i < channels[0].length; i++) {
      let sample = 0;
      for (const channel of channels) sample += channel[i] / channels.length;
      this.buffer[this.offset++] = sample;
      if (this.offset === this.buffer.length) {
        this.port.postMessage(this.buffer);
        this.buffer = new Float32Array(2048);
        this.offset = 0;
      }
    }
    return true;
  }
}
registerProcessor("jarvis-capture", CaptureProcessor);
