"""
email_sender.py
Sends a PDF invoice as an email attachment via SMTP (TLS).
"""

from __future__ import annotations

import smtplib
import time
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path


def send_invoice(
    *,
    to_email: str,
    customer_name: str,
    invoice_number: str,
    pdf_path: str | Path,
    company: dict,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    currency: str = "£",
    total_due: float = 0.0,
    retries: int = 3,
) -> None:
    """
    Send an invoice PDF to a customer via SMTP with TLS.

    Args:
        to_email:       Recipient email address.
        customer_name:  Recipient's display name.
        invoice_number: Invoice reference for the subject line.
        pdf_path:       Path to the generated PDF file.
        company:        Dict with keys name, email (used as sender).
        smtp_host:      SMTP server hostname.
        smtp_port:      SMTP server port (usually 587 for STARTTLS).
        smtp_user:      SMTP authentication username.
        smtp_password:  SMTP authentication password.
        currency:       Currency symbol for display in the email body.
        total_due:      Total amount owed (used in email body).
        retries:        Number of send attempts before raising.

    Raises:
        smtplib.SMTPException: If all retry attempts fail.
    """
    pdf_path = Path(pdf_path)
    company_name = company.get("name", "Billing")
    from_email    = company.get("email", smtp_user)

    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"Invoice {invoice_number} from {company_name}"
    msg["From"]    = f"{company_name} <{from_email}>"
    msg["To"]      = to_email

    # ---- HTML body ---------------------------------------------------------
    html_body = _build_html_body(
        customer_name=customer_name,
        invoice_number=invoice_number,
        company=company,
        currency=currency,
        total_due=total_due,
    )
    msg.attach(MIMEText(html_body, "html"))

    # ---- PDF attachment ----------------------------------------------------
    with open(pdf_path, "rb") as f:
        part = MIMEBase("application", "pdf")
        part.set_payload(f.read())

    encoders.encode_base64(part)
    part.add_header(
        "Content-Disposition",
        "attachment",
        filename=pdf_path.name,
    )
    msg.attach(part)

    # ---- Send with retry ---------------------------------------------------
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(smtp_user, smtp_password)
                server.sendmail(from_email, to_email, msg.as_bytes())
            return  # success
        except (smtplib.SMTPException, OSError) as exc:
            last_exc = exc
            if attempt < retries:
                wait = 2 ** attempt
                print(f"  [email] Attempt {attempt} failed ({exc}). Retrying in {wait}s…")
                time.sleep(wait)

    raise smtplib.SMTPException(
        f"Failed to send invoice {invoice_number} to {to_email} after {retries} attempts. "
        f"Last error: {last_exc}"
    )


# ---------------------------------------------------------------------------
# HTML email body
# ---------------------------------------------------------------------------

def _build_html_body(
    *,
    customer_name: str,
    invoice_number: str,
    company: dict,
    currency: str,
    total_due: float,
) -> str:
    company_name = company.get("name", "")
    company_email = company.get("email", "")
    company_phone = company.get("phone", "")

    total_str = f"{currency}{total_due:,.2f}" if total_due else "see attached PDF"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: Arial, sans-serif; background: #f4f4f4; margin: 0; padding: 0; }}
    .wrapper {{ max-width: 620px; margin: 32px auto; background: #ffffff;
                border-radius: 6px; overflow: hidden;
                box-shadow: 0 2px 8px rgba(0,0,0,.12); }}
    .header {{ background: #1A3557; color: #fff; padding: 28px 32px; }}
    .header h1 {{ margin: 0; font-size: 22px; }}
    .header p  {{ margin: 4px 0 0; font-size: 13px; opacity: .8; }}
    .accent {{ height: 4px; background: #F0A500; }}
    .body {{ padding: 28px 32px; color: #333; }}
    .body p {{ line-height: 1.6; margin: 0 0 14px; }}
    .amount-box {{ background: #D6E4F2; border-left: 4px solid #1A3557;
                   padding: 14px 18px; border-radius: 4px; margin: 20px 0; }}
    .amount-box .label {{ font-size: 12px; color: #555; text-transform: uppercase; }}
    .amount-box .amount {{ font-size: 24px; font-weight: bold; color: #1A3557; }}
    .footer {{ background: #f4f4f4; padding: 16px 32px; font-size: 11px;
               color: #888; text-align: center; border-top: 1px solid #e0e0e0; }}
    a {{ color: #2F6DAB; }}
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="header">
      <h1>{company_name}</h1>
      <p>Invoice Notification</p>
    </div>
    <div class="accent"></div>
    <div class="body">
      <p>Dear {customer_name},</p>
      <p>
        Please find attached your invoice <strong>{invoice_number}</strong>
        from <strong>{company_name}</strong>.
      </p>
      <div class="amount-box">
        <div class="label">Amount Due</div>
        <div class="amount">{total_str}</div>
      </div>
      <p>
        Your invoice is attached to this email as a PDF. If you have any
        questions regarding your invoice, please do not hesitate to contact
        our billing team.
      </p>
      <p>Thank you for your business.</p>
      <p>
        Kind regards,<br>
        <strong>{company_name}</strong><br>
        <a href="mailto:{company_email}">{company_email}</a>
        {f'&nbsp;|&nbsp; {company_phone}' if company_phone else ''}
      </p>
    </div>
    <div class="footer">
      {company_name} &nbsp;&bull;&nbsp; {company.get('address', '')}
      {', ' + company.get('city', '') if company.get('city') else ''}
      {', ' + company.get('postcode', '') if company.get('postcode') else ''}
    </div>
  </div>
</body>
</html>"""
