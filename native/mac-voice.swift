import Foundation
import AVFoundation
import Darwin
let synthesizer = AVSpeechSynthesizer()
if CommandLine.arguments.contains("--list") {
    let inventory = AVSpeechSynthesisVoice.speechVoices().filter { ["en-IN", "hi-IN"].contains($0.language) }.map { ["name": $0.name, "id": $0.identifier, "language": $0.language] }
    if let data = try? JSONSerialization.data(withJSONObject: inventory) { print(String(data: data, encoding: .utf8)!) }
    exit(0)
}
var busy = false
func emit(_ value: [String: Any]) {
    if let data = try? JSONSerialization.data(withJSONObject:value), let line = String(data:data,encoding:.utf8) { print(line); fflush(stdout) }
}
func u16(_ value: UInt16) -> Data { var n=value.littleEndian;return Data(bytes:&n,count:2) }
func u32(_ value: UInt32) -> Data { var n=value.littleEndian;return Data(bytes:&n,count:4) }
func handle(_ line: String) {
    guard !busy, line.utf8.count < 8000, let data=line.data(using:.utf8), let request=(try? JSONSerialization.jsonObject(with:data)) as? [String:Any], let text=request["text"] as? String, text.count <= 1200, let name=request["voice"] as? String, ["Rishi","Tara","Aman","Lekha"].contains(name), let voice=AVSpeechSynthesisVoice.speechVoices().first(where:{$0.name==name}) else {emit(["ok":false,"error":"Installed system voice unavailable or invalid request"]);return}
    busy=true
    let utterance=AVSpeechUtterance(string:text);utterance.voice=voice
    let pace=(request["pace"] as? Double) ?? 1.0
    utterance.rate=AVSpeechUtteranceDefaultSpeechRate / Float(max(0.8,min(1.4,pace)))
    var pcm=Data();var rate:Double=22050
    synthesizer.write(utterance) { buffer in
        guard let audio=buffer as? AVAudioPCMBuffer else {return}
        if audio.frameLength==0 {
            var wav=Data("RIFF".utf8);wav.append(u32(UInt32(pcm.count+36)));wav.append(Data("WAVEfmt ".utf8));wav.append(u32(16));wav.append(u16(1));wav.append(u16(1));wav.append(u32(UInt32(rate)));wav.append(u32(UInt32(rate)*2));wav.append(u16(2));wav.append(u16(16));wav.append(Data("data".utf8));wav.append(u32(UInt32(pcm.count)));wav.append(pcm)
            DispatchQueue.main.async {busy=false;emit(["ok":true,"wav":wav.base64EncodedString()])}
            return
        }
        rate=audio.format.sampleRate
        for i in 0..<Int(audio.frameLength) {
            var sample:Float=0
            if let channels=audio.floatChannelData {sample=channels[0][i]}
            else if let channels=audio.int16ChannelData {sample=Float(channels[0][i])/32768}
            let value=Int16(max(-32768,min(32767,sample*32767)))
            pcm.append(u16(UInt16(bitPattern:value)))
        }
    }
}
DispatchQueue.global().async {
    while let line=readLine() { DispatchQueue.main.async {handle(line)} }
    exit(0)
}
RunLoop.main.run()
