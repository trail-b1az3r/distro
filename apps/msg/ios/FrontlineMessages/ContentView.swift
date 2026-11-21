import SwiftUI

struct ContentView: View {
    @ObservedObject private var server = Server.shared
    @ObservedObject private var keepAlive = KeepAlive.shared
    @ObservedObject private var paired = PairedComputers.shared
    @ObservedObject private var composer = Composer.shared
    @State private var stayConnected = KeepAlive.shared.enabled

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Label(server.listening ? "Ready for your computer" : "Starting…",
                          systemImage: server.listening ? "checkmark.circle.fill" : "hourglass")
                    ForEach(server.computers, id: \.self) { name in
                        Label("Connected: \(name)", systemImage: "desktopcomputer")
                    }
                    if composer.waiting > 0 {
                        Label("\(composer.waiting) message(s) waiting to be sent", systemImage: "paperplane")
                    }
                    if !server.lastError.isEmpty {
                        Text(server.lastError).font(.footnote).foregroundStyle(.red)
                    }
                } footer: {
                    Text("On the computer, open Messages (frontline-msg), then the phone button: connect over the cable, or on this Wi-Fi by this iPhone's address.")
                }

                Section {
                    Toggle("Stay connected in the background", isOn: $stayConnected)
                        .onChange(of: stayConnected) { on in keepAlive.enabled = on }
                } footer: {
                    Text("Plays silence (it mixes with your music) so iOS keeps the app running, as SideStore does. "
                         + (keepAlive.running ? "Running." : "Not running."))
                }

                Section("Paired computers") {
                    if paired.all.isEmpty {
                        Text("None yet").foregroundStyle(.secondary)
                    }
                    ForEach(paired.all.sorted(by: { $0.value < $1.value }), id: \.key) { key, name in
                        Text(name)
                            .swipeActions { Button("Forget", role: .destructive) { paired.remove(key) } }
                    }
                }

                Section {
                    Text("iOS lets no app read your messages, so your computer gets them over Bluetooth (turn on Show Notifications for it in Bluetooth settings) and from backups over the cable. This app gives it your contacts and sends pictures for it: they open in Messages for you to tap Send.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Frontline Messages")
        }
        .sheet(item: $server.pairing) { request in
            VStack(spacing: 20) {
                Text("Pair with \(request.name)?").font(.title2.bold())
                Text("The computer shows this code. Pair only if they match.").multilineTextAlignment(.center)
                Text(String(request.code.prefix(3)) + " " + String(request.code.suffix(3)))
                    .font(.system(size: 44, weight: .bold, design: .monospaced))
                HStack {
                    Button("Cancel", role: .cancel) { request.decide(false); server.pairing = nil }
                        .buttonStyle(.bordered)
                    Button("Pair") { request.decide(true); server.pairing = nil }
                        .buttonStyle(.borderedProminent)
                }
            }
            .padding(32)
            .presentationDetents([.medium])
            .interactiveDismissDisabled()
        }
    }
}
