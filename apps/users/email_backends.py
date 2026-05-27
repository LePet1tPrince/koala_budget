from django.core.mail.backends.console import EmailBackend


class DevConsoleEmailBackend(EmailBackend):
    """
    Console email backend for development that decodes quoted-printable encoding
    in the plain-text body, so URLs appear on a single line and can be copied
    from Docker Compose log output without the web-1 | prefix breaking them.
    """

    def write_message(self, message):
        msg = message.message()

        lines = [
            f"To: {msg.get('To', '')}",
            f"Subject: {msg.get('Subject', '')}",
            "-" * 79,
        ]

        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    lines.append(payload.decode("utf-8", errors="replace"))

        lines.append("-" * 79)

        self.stream.write("\n".join(lines) + "\n")
        self.stream.flush()
