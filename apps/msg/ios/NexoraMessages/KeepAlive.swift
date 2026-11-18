import AVFoundation
import Foundation

/// Plays silence, so iOS keeps the app (and the computer's connection) running in the background, the way SideStore
/// keeps its VPN alive. It mixes with other audio, so music and calls are not interrupted, and it starts again after
/// an interruption (a call, Siri, another app taking the audio session).
final class KeepAlive: ObservableObject {
    static let shared = KeepAlive()
    @Published private(set) var running = false

    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private var attached = false
    private var observers: [NSObjectProtocol] = []

    var enabled: Bool {
        get { UserDefaults.standard.object(forKey: "keepAlive") as? Bool ?? true }
        set {
            UserDefaults.standard.set(newValue, forKey: "keepAlive")
            newValue ? start() : stop()
        }
    }

    private init() {
        let center = NotificationCenter.default
        observers.append(center.addObserver(forName: AVAudioSession.interruptionNotification, object: nil, queue: .main) { [weak self] note in
            guard let self, self.enabled,
                  let raw = note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
                  AVAudioSession.InterruptionType(rawValue: raw) == .ended else { return }
            self.start()
        })
        observers.append(center.addObserver(forName: AVAudioSession.mediaServicesWereResetNotification, object: nil, queue: .main) { [weak self] _ in
            guard let self, self.enabled else { return }
            self.attached = false
            self.start()
        })
        observers.append(center.addObserver(forName: .AVAudioEngineConfigurationChange, object: engine, queue: .main) { [weak self] _ in
            guard let self, self.enabled else { return }
            self.start()
        })
    }

    func start() {
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.playback, mode: .default, options: [.mixWithOthers])
            try session.setActive(true)
            guard let format = AVAudioFormat(standardFormatWithSampleRate: 44_100, channels: 1),
                  let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 44_100) else { return }
            buffer.frameLength = buffer.frameCapacity
            if let samples = buffer.floatChannelData?[0] {
                samples.initialize(repeating: 0, count: Int(buffer.frameLength))
            }
            if !attached {
                engine.attach(player)
                engine.connect(player, to: engine.mainMixerNode, format: format)
                attached = true
            }
            if !engine.isRunning {
                try engine.start()
            }
            player.stop()
            player.scheduleBuffer(buffer, at: nil, options: .loops)
            player.play()
            running = true
        } catch {
            running = false
        }
    }

    func stop() {
        player.stop()
        engine.stop()
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        running = false
    }
}
