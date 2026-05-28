import logging
from html import escape
from flask_mail import Message, Mail
from flask import current_app

logger = logging.getLogger(__name__)

class EmailService:
    """Service for sending emails"""

    def __init__(self, mail: Mail = None):
        self.mail = mail

    def send_verification_email(self, to_email: str, token: str):
        """Send a verification email to a new user"""
        if not self.mail:
            logger.warning("Mail service not initialized, skipping email sending")
            return

        frontend_url = current_app.config.get("FRONTEND_URL", "http://localhost")
        verification_url = f"{frontend_url}/verify-email/{token}"

        subject = "Verify your WebHDP account"

        # Plain text fallback
        body_text = (
            f"Welcome to WebHDP!\n\n"
            f"Please verify your account by clicking the following link:\n"
            f"{verification_url}\n\n"
            f"NOTICE: WebHDP is in a very early alpha phase and used for testing purposes only at this stage of development.\n\n"
            f"If you did not create an account, please ignore this email."
        )

        # HTML Version
        body_html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 5px; background-color: #f9f9f9;">
            <div style="text-align: center; margin-bottom: 20px;">
                <h2 style="color: #333; margin: 0;">Welcome to WebHDP (Alpha)</h2>
            </div>

            <div style="background-color: #ffffff; padding: 20px; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">
                <p style="font-size: 16px; color: #555;">Please verify your account to continue using the WebHDP (Alpha).</p>

                <div style="text-align: center; margin: 30px 0;">
                    <a href="{verification_url}" style="background-color: #007bff; color: white; padding: 12px 25px; text-decoration: none; border-radius: 5px; font-weight: bold; font-size: 16px;">Verify Account</a>
                </div>

                <p style="font-size: 14px; color: #777;">Or paste this link into your browser:</p>
                <p style="font-size: 13px; color: #007bff; word-break: break-all;">{verification_url}</p>
            </div>

            <div style="margin-top: 30px; padding: 15px; background-color: #fff3cd; color: #856404; border: 1px solid #ffeeba; border-radius: 5px; text-align: center;">
                <strong>Notice:</strong> WebHDP is in a very early alpha phase and used for testing purposes only at this stage of development.
            </div>

            <div style="text-align: center; margin-top: 30px; border-top: 1px solid #eee; padding-top: 20px;">
                <p style="font-size: 12px; color: #999;">If you did not create an account, please ignore this email.</p>
            </div>
        </div>
        """

        msg = Message(
            subject=subject,
            recipients=[to_email],
            body=body_text,
            html=body_html
        )

        try:
            self.mail.send(msg)
            logger.info(f"Verification email sent to {to_email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send verification email to {to_email}: {str(e)}")
            return False

    def send_login_mfa_code_email(self, to_email: str, code: str, expires_minutes: int):
        """Send the login MFA code email."""
        if not self.mail:
            logger.warning("Mail service not initialized, skipping MFA email")
            return False

        safe_code = escape(str(code))
        safe_minutes = escape(str(expires_minutes))
        subject = "Your WebHDP login code"
        body_text = (
            f"Your WebHDP verification code is {code}\n\n"
            f"This code expires in {expires_minutes} minutes.\n\n"
            f"If you did not try to sign in, you can ignore this email."
        )
        body_html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <p style="font-size: 18px; color: #111827; margin: 0 0 16px;">
                Your WebHDP verification code is <strong style="letter-spacing: 0.18em;">{safe_code}</strong>
            </p>
            <p style="color: #374151; line-height: 1.5;">This code expires in {safe_minutes} minutes.</p>
            <p style="font-size: 12px; color: #6b7280; border-top: 1px solid #e5e7eb; padding-top: 16px;">
                If you did not try to sign in, you can ignore this email.
            </p>
        </div>
        """

        msg = Message(
            subject=subject,
            recipients=[to_email],
            body=body_text,
            html=body_html,
        )

        try:
            self.mail.send(msg)
            logger.info(f"Login MFA email sent to {to_email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send login MFA email to {to_email}: {str(e)}")
            return False

    def send_notification_email(self, to_email: str, notification: dict):
        """Send an immediate notification email when the user opted in."""
        if not self.mail:
            logger.warning("Mail service not initialized, skipping notification email")
            return False

        title = str(notification.get("title") or "WebHDP notification")
        body = str(notification.get("body") or "")
        category = str(notification.get("category_label") or notification.get("category") or "Notification")
        title_html = escape(title)
        body_html_text = escape(body)
        category_html = escape(category)
        frontend_url = current_app.config.get("FRONTEND_URL", "http://localhost").rstrip("/")
        action_url = str(notification.get("action_url") or "")
        action_link = f"{frontend_url}{action_url}" if action_url.startswith("/") else action_url

        body_text = f"{title}\n\n{body}\n\nCategory: {category}"
        if action_link:
            body_text = f"{body_text}\n\nOpen in WebHDP: {action_link}"

        action_html = ""
        if action_link:
            action_html = f"""
                <div style="margin: 24px 0;">
                    <a href="{escape(action_link, quote=True)}" style="background-color: #4f46e5; color: white; padding: 10px 16px; text-decoration: none; border-radius: 5px; font-weight: bold;">Open in WebHDP</a>
                </div>
            """

        body_html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <p style="font-size: 12px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.08em;">{category_html}</p>
            <h2 style="color: #111827; margin: 0 0 12px;">{title_html}</h2>
            <p style="color: #374151; line-height: 1.5;">{body_html_text}</p>
            {action_html}
            <p style="font-size: 12px; color: #6b7280; border-top: 1px solid #e5e7eb; padding-top: 16px;">
                You received this because email notifications are enabled in your WebHDP notification preferences.
            </p>
        </div>
        """

        msg = Message(
            subject=f"WebHDP: {title}",
            recipients=[to_email],
            body=body_text,
            html=body_html,
        )

        try:
            self.mail.send(msg)
            logger.info(f"Notification email sent to {to_email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send notification email to {to_email}: {str(e)}")
            return False

    def send_notification_digest_email(self, to_email: str, notifications: list[dict]):
        """Send a grouped notification digest email."""
        if not self.mail:
            logger.warning("Mail service not initialized, skipping notification digest")
            return False
        if not notifications:
            return True

        frontend_url = current_app.config.get("FRONTEND_URL", "http://localhost").rstrip("/")
        body_lines = ["Your WebHDP notification digest", ""]
        html_items = []
        for item in notifications:
            title = str(item.get("title") or "Notification")
            body = str(item.get("body") or "")
            category = str(item.get("category_label") or item.get("category") or "Notification")
            action_url = str(item.get("action_url") or "")
            action_link = f"{frontend_url}{action_url}" if action_url.startswith("/") else action_url
            body_lines.append(f"- [{category}] {title}")
            if body:
                body_lines.append(f"  {body}")
            if action_link:
                body_lines.append(f"  {action_link}")

            link_html = ""
            if action_link:
                link_html = f'<a href="{escape(action_link, quote=True)}" style="color: #4f46e5;">Open</a>'
            html_items.append(
                f"""
                <li style="margin-bottom: 16px;">
                    <p style="font-size: 12px; color: #6b7280; margin: 0 0 4px;">{escape(category)}</p>
                    <p style="font-weight: bold; color: #111827; margin: 0 0 4px;">{escape(title)}</p>
                    <p style="color: #374151; margin: 0 0 6px;">{escape(body)}</p>
                    {link_html}
                </li>
                """
            )

        body_text = "\n".join(body_lines)
        body_html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 640px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #111827;">Your WebHDP notification digest</h2>
            <p style="color: #374151;">{len(notifications)} notification{'s' if len(notifications) != 1 else ''} are ready for review.</p>
            <ul style="padding-left: 20px;">{''.join(html_items)}</ul>
            <p style="font-size: 12px; color: #6b7280; border-top: 1px solid #e5e7eb; padding-top: 16px;">
                You received this because notification digests are enabled in your WebHDP preferences.
            </p>
        </div>
        """

        msg = Message(
            subject=f"WebHDP notification digest ({len(notifications)})",
            recipients=[to_email],
            body=body_text,
            html=body_html,
        )

        try:
            self.mail.send(msg)
            logger.info(f"Notification digest sent to {to_email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send notification digest to {to_email}: {str(e)}")
            return False
