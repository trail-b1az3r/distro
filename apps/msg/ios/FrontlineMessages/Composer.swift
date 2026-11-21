import MessageUI
import UIKit
import UniformTypeIdentifiers

/// Sending what the computer asks for: iOS lets no app send a message by itself, so the message (and its picture)
/// is filled in in Messages' own sheet, and you tap Send. When the app is in the background, a notification brings
/// it forward; drafts wait in order.
final class Composer: NSObject, ObservableObject, MFMessageComposeViewControllerDelegate {
    static let shared = Composer()

    struct Draft {
        let to: [String]
        let text: String
        let image: Data?
        let filename: String
    }

    @Published private(set) var waiting = 0
    private var queue: [(Draft, (String) -> Void)] = []
    private var current: ((String) -> Void)?

    func enqueue(_ draft: Draft, done: @escaping (String) -> Void) {
        guard MFMessageComposeViewController.canSendText() else { done("failed"); return }
        queue.append((draft, done))
        waiting = queue.count + (current == nil ? 0 : 1)
        if UIApplication.shared.applicationState == .active {
            presentNext()
        } else {
            Notifier.draft(to: draft.to.joined(separator: ", "), hasPicture: draft.image != nil)
        }
    }

    /// Called when the app comes forward.
    func presentNext() {
        guard current == nil, !queue.isEmpty, let top = Composer.topController() else { return }
        let (draft, done) = queue.removeFirst()
        let sheet = MFMessageComposeViewController()
        sheet.messageComposeDelegate = self
        sheet.recipients = draft.to
        sheet.body = draft.text
        if let image = draft.image {
            let ext = (draft.filename as NSString).pathExtension
            let type = UTType(filenameExtension: ext)?.identifier ?? UTType.jpeg.identifier
            sheet.addAttachmentData(image, typeIdentifier: type, filename: draft.filename)
        }
        current = done
        top.present(sheet, animated: true)
    }

    func messageComposeViewController(_ controller: MFMessageComposeViewController,
                                      didFinishWith result: MessageComposeResult) {
        let text: String
        switch result {
        case .sent: text = "sent"
        case .cancelled: text = "cancelled"
        default: text = "failed"
        }
        controller.dismiss(animated: true) {
            self.current?(text)
            self.current = nil
            self.waiting = self.queue.count
            self.presentNext()
        }
    }

    static func topController() -> UIViewController? {
        let window = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
            .flatMap { $0.windows }.first { $0.isKeyWindow }
        var top = window?.rootViewController
        while let next = top?.presentedViewController { top = next }
        return top
    }
}
