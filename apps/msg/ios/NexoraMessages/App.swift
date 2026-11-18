import SwiftUI

@main
struct NexoraMessagesApp: App {
    @Environment(\.scenePhase) private var phase

    init() {
        Notifier.requestPermission()
        Server.shared.start()
        if KeepAlive.shared.enabled { KeepAlive.shared.start() }
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .onChange(of: phase) { newPhase in
                    if newPhase == .active {
                        Server.shared.start()
                        Composer.shared.presentNext()
                    }
                }
        }
    }
}
