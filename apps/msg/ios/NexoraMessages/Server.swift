import CryptoKit
import Foundation
import Network
import UIKit

/// Listens on port 47800 (reached over the USB cable through usbmuxd, or on Wi-Fi, where it is advertised with
/// Bonjour as _nexoramsg._tcp) and serves the computer: contacts, and messages to send.
final class Server: ObservableObject {
    static let port: NWEndpoint.Port = 47800
    static let shared = Server()

    @Published var listening = false
    @Published var computers: [String] = []             // connected now
    @Published var pairing: PairingRequest?
    @Published var lastError = ""
    /// Read on the main thread once (UIKit), used by the connections' queue.
    private(set) var deviceName = "iPhone"

    private var listener: NWListener?
    private var links: [ObjectIdentifier: Link] = [:]
    let queue = DispatchQueue(label: "org.nexora.messages.server")

    struct PairingRequest: Identifiable {
        let id = UUID()
        let name: String
        let code: String
        let decide: (Bool) -> Void
    }

    func start() {
        guard listener == nil else { return }
        deviceName = UIDevice.current.name
        do {
            let params = NWParameters.tcp
            params.allowLocalEndpointReuse = true
            let listener = try NWListener(using: params, on: Server.port)
            listener.service = NWListener.Service(name: deviceName, type: "_nexoramsg._tcp")
            listener.stateUpdateHandler = { [weak self] state in
                DispatchQueue.main.async {
                    switch state {
                    case .ready: self?.listening = true
                    case .failed(let error):
                        self?.listening = false
                        self?.lastError = error.localizedDescription
                        self?.listener = nil
                        // Try again shortly: the port may still be held by the last run.
                        DispatchQueue.main.asyncAfter(deadline: .now() + 3) { self?.start() }
                    case .cancelled: self?.listening = false
                    default: break
                    }
                }
            }
            listener.newConnectionHandler = { [weak self] connection in
                guard let self else { return }
                let link = Link(connection: connection, server: self)
                self.links[ObjectIdentifier(link)] = link
                link.start()
            }
            listener.start(queue: queue)
            self.listener = listener
        } catch {
            lastError = error.localizedDescription
        }
    }

    func closed(_ link: Link) {
        queue.async { self.links.removeValue(forKey: ObjectIdentifier(link)) }
        refreshComputers()
    }

    func refreshComputers() {
        queue.async {
            let names = self.links.values.filter { $0.ready }.map { $0.computerName }
            DispatchQueue.main.async { self.computers = names }
        }
    }
}

/// One computer's connection: the plaintext hello, then encrypted JSON frames (4-byte big-endian length first).
final class Link {
    let connection: NWConnection
    unowned let server: Server
    private var key: SymmetricKey?
    private var sent: UInt64 = 0
    private var received: UInt64 = 0
    private(set) var ready = false
    private(set) var computerName = "Computer"
    private var computerKey = ""

    init(connection: NWConnection, server: Server) {
        self.connection = connection
        self.server = server
    }

    func start() {
        connection.stateUpdateHandler = { [weak self] state in
            switch state {
            case .failed, .cancelled:
                if let self { self.server.closed(self) }
            default: break
            }
        }
        connection.start(queue: server.queue)
        readFrame { [weak self] data in self?.hello(data) }
    }

    // MARK: frames

    private func readFrame(_ handle: @escaping (Data) -> Void) {
        connection.receive(minimumIncompleteLength: 4, maximumLength: 4) { [weak self] head, _, done, error in
            guard let self, let head, head.count == 4, error == nil else { self?.close(); return }
            let length = head.reduce(0) { ($0 << 8) | Int($1) }
            guard length > 0, length <= 64 * 1024 * 1024 else { self.close(); return }
            self.readExactly(length, into: Data()) { body in
                guard let body else { self.close(); return }
                handle(body)
            }
            _ = done
        }
    }

    private func readExactly(_ count: Int, into buffer: Data, _ done: @escaping (Data?) -> Void) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: count - buffer.count) { [weak self] data, _, end, error in
            guard let self, let data, error == nil else { done(nil); return }
            let all = buffer + data
            if all.count == count { done(all) } else if end { done(nil) } else { self.readExactly(count, into: all, done) }
        }
    }

    private func writeFrame(_ object: [String: Any]) {
        guard var data = try? JSONSerialization.data(withJSONObject: object) else { return }
        if let key {
            guard let box = try? ChaChaPoly.seal(data, using: key, nonce: LinkCrypto.nonce("P2D", sent)) else { return }
            sent += 1
            data = box.ciphertext + box.tag
        }
        var length = UInt32(data.count).bigEndian
        connection.send(content: Data(bytes: &length, count: 4) + data, completion: .contentProcessed { _ in })
    }

    func send(_ object: [String: Any]) {
        server.queue.async { self.writeFrame(object) }
    }

    private func close() {
        connection.cancel()
    }

    // MARK: the hello and pairing

    private func hello(_ data: Data) {
        guard let hello = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              hello["hello"] as? String == "nexora-msg",
              let pubText = hello["pub"] as? String, let pub = Data(base64Encoded: pubText),
              let nonceText = hello["nonce"] as? String, let desktopNonce = Data(base64Encoded: nonceText),
              let peer = try? Curve25519.KeyAgreement.PublicKey(rawRepresentation: pub) else { close(); return }
        let me = Identity.key()
        guard let secret = try? me.sharedSecretFromKeyAgreement(with: peer) else { close(); return }
        let shared = secret.withUnsafeBytes { Data($0) }
        let phoneNonce = LinkCrypto.randomBytes(16)
        computerName = hello["name"] as? String ?? "Computer"
        computerKey = pubText
        let paired = PairedComputers.shared.contains(pubText)
        writeFrame(["hello": "nexora-msg-ios", "v": 1, "pub": me.publicKey.rawRepresentation.base64EncodedString(),
                    "nonce": phoneNonce.base64EncodedString(), "paired": paired, "name": server.deviceName])
        key = LinkCrypto.sessionKey(shared, desktopNonce: desktopNonce, phoneNonce: phoneNonce)
        if paired {
            ready = true
            server.refreshComputers()
            loop()
        } else {
            let code = LinkCrypto.pairingCode(shared)
            DispatchQueue.main.async {
                self.server.pairing = Server.PairingRequest(name: self.computerName, code: code) { yes in
                    self.server.queue.async {
                        if yes {
                            PairedComputers.shared.add(self.computerKey, name: self.computerName)
                            self.ready = true
                            self.writeFrame(["event": "paired"])
                            self.server.refreshComputers()
                            self.loop()
                        } else {
                            self.close()
                        }
                    }
                }
                Notifier.pairing(name: self.computerName, code: code)
            }
        }
    }

    // MARK: requests

    private func loop() {
        readFrame { [weak self] data in
            guard let self, let key = self.key else { return }
            guard data.count >= 16,
                  let box = try? ChaChaPoly.SealedBox(nonce: LinkCrypto.nonce("D2P", self.received),
                                                      ciphertext: data.prefix(data.count - 16), tag: data.suffix(16)),
                  let plain = try? ChaChaPoly.open(box, using: key),
                  let request = try? JSONSerialization.jsonObject(with: plain) as? [String: Any] else {
                self.close()
                return
            }
            self.received += 1
            self.handle(request)
            self.loop()
        }
    }

    private func reply(_ id: Any?, data: Any? = nil, error: String? = nil) {
        var out: [String: Any] = ["id": id ?? NSNull(), "ok": error == nil]
        if let data { out["data"] = data }
        if let error { out["error"] = error }
        writeFrame(out)
    }

    private func handle(_ request: [String: Any]) {
        let id = request["id"]
        switch request["op"] as? String ?? "" {
        case "ping":
            DispatchQueue.main.async {
                UIDevice.current.isBatteryMonitoringEnabled = true
                let battery = UIDevice.current.batteryLevel
                self.send(["id": id ?? NSNull(), "ok": true, "data": ["battery": battery]])
            }
        case "contacts":
            ContactsExport.all { result in
                self.server.queue.async {
                    switch result {
                    case .success(let people): self.reply(id, data: people)
                    case .failure(let error): self.reply(id, error: error.localizedDescription)
                    }
                }
            }
        case "send":
            let to = request["to"] as? [String] ?? []
            let text = request["text"] as? String ?? ""
            let image = (request["image"] as? String).flatMap { Data(base64Encoded: $0) }
            let filename = request["filename"] as? String ?? "picture.jpg"
            guard !to.isEmpty else { reply(id, error: "nobody to send to"); return }
            DispatchQueue.main.async {
                Composer.shared.enqueue(Composer.Draft(to: to, text: text, image: image, filename: filename)) { result in
                    self.server.queue.async { self.reply(id, data: ["result": result]) }
                }
            }
        default:
            reply(id, error: "unknown request")
        }
    }
}
