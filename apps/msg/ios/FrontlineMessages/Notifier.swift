import UserNotifications

/// Local notifications: a computer wants to pair, or a message from the computer is waiting to be sent.
enum Notifier {
    static func requestPermission() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }

    private static func post(_ id: String, title: String, body: String) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: id, content: content, trigger: nil))
    }

    static func pairing(name: String, code: String) {
        post("pair", title: "Pair with \(name)?", body: "Open Frontline Messages and check the code \(code).")
    }

    static func draft(to: String, hasPicture: Bool) {
        post("draft-\(UUID().uuidString)", title: hasPicture ? "Picture ready to send" : "Message ready to send",
             body: "To \(to). Tap to open it in Messages.")
    }
}
