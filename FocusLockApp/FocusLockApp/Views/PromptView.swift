import SwiftUI

/// The styled floating panel that replaces every interactive osascript dialog.
/// Looks consistent with the rest of Locus: serif headline, accent button,
/// soft surface card. One-line reason input as requested.
struct PromptView: View {
    let prompt: Prompt
    @State private var reason: String = ""
    @State private var code: String = ""
    @FocusState private var inputFocused: Bool

    var body: some View {
        Group {
            switch prompt.type {
            case "ask_reason":     askReasonBody
            case "ask_off_topic":  askOffTopicBody
            case "ask_override":   askOverrideBody
            case "show_result":    showResultBody
            case "long_session":   longSessionBody
            default:               unknownBody
            }
        }
        .frame(width: 460)
        .background(Theme.surface)
        .preferredColorScheme(nil)
        .onAppear { inputFocused = true }
    }

    // MARK: - ask_reason

    private var askReasonBody: some View {
        VStack(spacing: 0) {
            promptHeader(
                icon: prompt.blocked_type == "app" ? "app.dashed" : "globe",
                tint: .red,
                title: prompt.blocked_name ?? "Blocked",
                subtitle: "Blocked during \(prompt.session_name ?? "your session")"
            )

            VStack(alignment: .leading, spacing: 12) {
                Text("Why do you need access?")
                    .font(.system(size: 13, weight: .semibold))
                Text("Be specific — AI will evaluate your reason.")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)

                TextField("e.g. Looking up the formula for kinetic energy", text: $reason)
                    .textFieldStyle(.roundedBorder)
                    .font(.system(size: 13))
                    .focused($inputFocused)
                    .onSubmit(submitReason)
            }
            .padding(.horizontal, 22)
            .padding(.top, 4)
            .padding(.bottom, 18)

            footer {
                Button("Cancel") { respond(action: "cancel") }
                    .buttonStyle(SecondaryPromptButtonStyle())
                Button("Override") { respond(action: "override") }
                    .buttonStyle(SecondaryPromptButtonStyle())
                Button("Submit", action: submitReason)
                    .buttonStyle(PromptPrimaryButtonStyle())
                    .keyboardShortcut(.defaultAction)
                    .disabled(reason.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
    }

    // MARK: - ask_off_topic

    private var askOffTopicBody: some View {
        VStack(spacing: 0) {
            promptHeader(
                icon: "exclamationmark.triangle.fill",
                tint: .orange,
                title: "Off-topic detected",
                subtitle: prompt.blocked_name ?? ""
            )

            VStack(alignment: .leading, spacing: 10) {
                if let title = prompt.tab_title, !title.isEmpty {
                    HStack(alignment: .top, spacing: 6) {
                        Image(systemName: "doc.text")
                            .foregroundStyle(.secondary)
                            .font(.system(size: 11))
                            .padding(.top, 2)
                        Text(title)
                            .font(.system(size: 12))
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                    }
                }
                if let r = prompt.ai_reason, !r.isEmpty {
                    Text(r)
                        .font(.system(size: 12))
                        .foregroundStyle(.primary)
                        .padding(10)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Theme.accentMuted, in: RoundedRectangle(cornerRadius: 8))
                }
                Text("Why are you viewing this?")
                    .font(.system(size: 13, weight: .semibold))
                    .padding(.top, 4)
                TextField("e.g. The video covers mitosis stages", text: $reason)
                    .textFieldStyle(.roundedBorder)
                    .font(.system(size: 13))
                    .focused($inputFocused)
                    .onSubmit(submitReason)
            }
            .padding(.horizontal, 22)
            .padding(.top, 4)
            .padding(.bottom, 18)

            footer {
                Button("Cancel") { respond(action: "cancel") }
                    .buttonStyle(SecondaryPromptButtonStyle())
                Button("Submit", action: submitReason)
                    .buttonStyle(PromptPrimaryButtonStyle())
                    .keyboardShortcut(.defaultAction)
                    .disabled(reason.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
    }

    // MARK: - ask_override

    private var askOverrideBody: some View {
        VStack(spacing: 0) {
            promptHeader(
                icon: "key.fill",
                tint: Theme.accent,
                title: "Enter Override Code",
                subtitle: "Bypass Locus for this session"
            )

            VStack(alignment: .leading, spacing: 10) {
                if prompt.is_pi_hint == true {
                    Text("Hint: it's the first 100 digits of π")
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                }
                SecureField("override code", text: $code)
                    .textFieldStyle(.roundedBorder)
                    .font(.system(size: 13, design: .monospaced))
                    .focused($inputFocused)
                    .onSubmit(submitCode)
            }
            .padding(.horizontal, 22)
            .padding(.top, 4)
            .padding(.bottom, 18)

            footer {
                Button("Cancel") { respond(action: "cancel") }
                    .buttonStyle(SecondaryPromptButtonStyle())
                Button("Unlock", action: submitCode)
                    .buttonStyle(PromptPrimaryButtonStyle())
                    .keyboardShortcut(.defaultAction)
                    .disabled(code.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
    }

    // MARK: - show_result

    private var showResultBody: some View {
        VStack(spacing: 0) {
            let approved = prompt.approved == true
            promptHeader(
                icon: approved ? "checkmark.seal.fill" : "xmark.octagon.fill",
                tint: approved ? .green : .red,
                title: approved ? "Access Granted" : "Access Denied",
                subtitle: prompt.target_name ?? ""
            )

            VStack(alignment: .leading, spacing: 12) {
                Text(prompt.explanation ?? "")
                    .font(.system(size: 13))
                    .foregroundStyle(.primary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                if approved, let m = prompt.minutes, m > 0 {
                    HStack(spacing: 6) {
                        Image(systemName: "clock.fill")
                            .font(.system(size: 11))
                        Text("Allowed for \(m) minutes")
                            .font(.system(size: 12, weight: .medium))
                    }
                    .foregroundStyle(Theme.accent)
                    .padding(8)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Theme.accentMuted, in: RoundedRectangle(cornerRadius: 8))
                }
            }
            .padding(.horizontal, 22)
            .padding(.top, 4)
            .padding(.bottom, 18)

            footer {
                Button("OK") { respond(action: "ok") }
                    .buttonStyle(PromptPrimaryButtonStyle())
                    .keyboardShortcut(.defaultAction)
            }
        }
    }

    // MARK: - long_session

    private var longSessionBody: some View {
        VStack(spacing: 0) {
            promptHeader(
                icon: "clock.badge.exclamationmark",
                tint: .orange,
                title: "Still focusing?",
                subtitle: prompt.session_name ?? "Focus Session"
            )

            VStack(alignment: .leading, spacing: 8) {
                Text("Your session has been running for over 5 hours.")
                    .font(.system(size: 13))
                    .foregroundStyle(.primary)
                Text("If you don't respond, the session will end automatically.")
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 22)
            .padding(.top, 4)
            .padding(.bottom, 18)

            footer {
                Button("End Session") { respond(action: "end") }
                    .buttonStyle(SecondaryPromptButtonStyle())
                Button("Keep Going") { respond(action: "continue") }
                    .buttonStyle(PromptPrimaryButtonStyle())
                    .keyboardShortcut(.defaultAction)
            }
        }
    }

    private var unknownBody: some View {
        VStack(spacing: 16) {
            Text("Unknown prompt").font(.system(size: 14, weight: .semibold))
            Button("Dismiss") { respond(action: "cancel") }
                .buttonStyle(PromptPrimaryButtonStyle())
        }
        .padding(24)
    }

    // MARK: - shared chrome

    private func promptHeader(icon: String, tint: Color, title: String, subtitle: String) -> some View {
        VStack(spacing: 12) {
            ZStack {
                Circle().fill(tint.opacity(0.12)).frame(width: 56, height: 56)
                Image(systemName: icon)
                    .font(.system(size: 24, weight: .semibold))
                    .foregroundStyle(tint)
            }
            VStack(spacing: 4) {
                Text(title)
                    .font(.serif(24))
                    .multilineTextAlignment(.center)
                if !subtitle.isEmpty {
                    Text(subtitle)
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                        .lineLimit(2)
                }
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 28)
        .padding(.bottom, 18)
        .padding(.horizontal, 22)
    }

    private func footer<Content: View>(@ViewBuilder _ content: () -> Content) -> some View {
        HStack(spacing: 10) {
            Spacer()
            content()
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 14)
        .background(Theme.surface.opacity(0.6))
        .overlay(Rectangle().fill(Theme.border).frame(height: 1), alignment: .top)
    }

    // MARK: - actions

    private func submitReason() {
        let r = reason.trimmingCharacters(in: .whitespaces)
        if r.isEmpty { return }
        respond(action: "submit", reason: r)
    }

    private func submitCode() {
        let c = code.trimmingCharacters(in: .whitespaces)
        if c.isEmpty { return }
        respond(action: "submit", code: c)
    }

    private func respond(action: String, reason: String = "", code: String = "") {
        let resp = PromptResponse(id: prompt.id, action: action, reason: reason, code: code)
        PromptCenter.shared.respond(resp)
    }
}

// MARK: - Button styles tuned for the prompt panel

private struct PromptPrimaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 13, weight: .semibold))
            .foregroundStyle(.white)
            .padding(.horizontal, 18)
            .padding(.vertical, 9)
            .background(
                RoundedRectangle(cornerRadius: 8)
                    .fill(Theme.accent.opacity(configuration.isPressed ? 0.78 : 1.0))
            )
            .opacity(isEnabled ? 1.0 : 0.45)
    }
    @Environment(\.isEnabled) private var isEnabled: Bool
}

private struct SecondaryPromptButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 13, weight: .medium))
            .foregroundStyle(.primary)
            .padding(.horizontal, 14)
            .padding(.vertical, 9)
            .background(
                RoundedRectangle(cornerRadius: 8)
                    .fill(configuration.isPressed ? Theme.border : Color.clear)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 8)
                    .stroke(Theme.border, lineWidth: 1)
            )
    }
}
