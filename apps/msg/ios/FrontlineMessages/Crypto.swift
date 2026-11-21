import CryptoKit
import Foundation
import Security

/// The same protocol as frontline_msg/companion.py: X25519 keys, a six-digit pairing code from the shared secret, and a
/// ChaCha20-Poly1305 key per connection (HKDF-SHA256 over the shared secret, salted with both sides' nonces).
enum LinkCrypto {
    static func hkdf(_ secret: Data, salt: Data, info: String, count: Int) -> Data {
        let key = HKDF<SHA256>.deriveKey(inputKeyMaterial: SymmetricKey(data: secret), salt: salt,
                                         info: Data(info.utf8), outputByteCount: count)
        return key.withUnsafeBytes { Data($0) }
    }

    static func pairingCode(_ shared: Data) -> String {
        let bytes = hkdf(shared, salt: Data(), info: "nexora-msg v1 code", count: 4)
        let value = bytes.reduce(UInt32(0)) { ($0 << 8) | UInt32($1) }
        return String(format: "%06d", value % 1_000_000)
    }

    static func sessionKey(_ shared: Data, desktopNonce: Data, phoneNonce: Data) -> SymmetricKey {
        SymmetricKey(data: hkdf(shared, salt: desktopNonce + phoneNonce, info: "nexora-msg v1 key", count: 32))
    }

    static func nonce(_ direction: String, _ counter: UInt64) -> ChaChaPoly.Nonce {
        var data = Data(direction.utf8)            // "D2P\0" or "P2D\0"
        data.append(0)
        var big = counter.bigEndian
        data.append(Data(bytes: &big, count: 8))
        return try! ChaChaPoly.Nonce(data: data)
    }

    static func randomBytes(_ count: Int) -> Data {
        var data = Data(count: count)
        _ = data.withUnsafeMutableBytes { SecRandomCopyBytes(kSecRandomDefault, count, $0.baseAddress!) }
        return data
    }
}

/// This phone's key, kept in the Keychain (this device only).
enum Identity {
    private static let account = "org.nexora.messages.identity"

    static func key() -> Curve25519.KeyAgreement.PrivateKey {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrAccount as String: account,
                                    kSecReturnData as String: true]
        var item: CFTypeRef?
        if SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess, let data = item as? Data,
           let key = try? Curve25519.KeyAgreement.PrivateKey(rawRepresentation: data) {
            return key
        }
        let key = Curve25519.KeyAgreement.PrivateKey()
        let add: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrAccount as String: account,
                                  kSecValueData as String: key.rawRepresentation,
                                  kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly]
        SecItemAdd(add as CFDictionary, nil)
        return key
    }
}

/// Computers this phone was paired with: their public keys (base64) and names.
final class PairedComputers: ObservableObject {
    static let shared = PairedComputers()
    @Published private(set) var all: [String: String]

    private init() {
        all = UserDefaults.standard.dictionary(forKey: "paired") as? [String: String] ?? [:]
    }

    func contains(_ key: String) -> Bool { all[key] != nil }

    func add(_ key: String, name: String) {
        all[key] = name
        UserDefaults.standard.set(all, forKey: "paired")
    }

    func remove(_ key: String) {
        all.removeValue(forKey: key)
        UserDefaults.standard.set(all, forKey: "paired")
    }
}
