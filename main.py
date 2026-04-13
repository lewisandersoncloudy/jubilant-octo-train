#!/usr/bin/env python3
"""
main.py  –  Invoice Generator
==============================
Reads an Excel orders file, groups rows by customer, generates PDF invoices,
and (optionally) emails each one to the customer.

Usage
-----
  # Generate PDFs only (no email):
  python main.py orders.xlsx

  # Generate PDFs and send emails:
  python main.py orders.xlsx --send-email

  # Dry run – show what would be processed without creating any files:
  python main.py orders.xlsx --dry-run

  # Custom output directory:
  python main.py orders.xlsx --output invoices/

  # Preview a single customer (by email):
  python main.py orders.xlsx --filter customer@example.com
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from excel_reader import load_orders
from invoice_generator import generate_invoice
from email_sender import send_invoice

# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

load_dotenv()


def _require_env(key: str) -> str:
    value = os.getenv(key, "").strip()
    if not value:
        print(f"[error] Missing required environment variable: {key}")
        print(f"        Copy .env.example to .env and fill in your details.")
        sys.exit(1)
    return value


def _get_company() -> dict:
    return {
        "name":     os.getenv("COMPANY_NAME",    "Your Company"),
        "address":  os.getenv("COMPANY_ADDRESS", ""),
        "city":     os.getenv("COMPANY_CITY",    ""),
        "postcode": os.getenv("COMPANY_POSTCODE",""),
        "country":  os.getenv("COMPANY_COUNTRY", ""),
        "email":    os.getenv("COMPANY_EMAIL",   ""),
        "phone":    os.getenv("COMPANY_PHONE",   ""),
        "vat":      os.getenv("COMPANY_VAT",     ""),
    }


def _get_smtp() -> dict:
    return {
        "host":     _require_env("SMTP_HOST"),
        "port":     int(os.getenv("SMTP_PORT", "587")),
        "user":     _require_env("SMTP_USER"),
        "password": _require_env("SMTP_PASSWORD"),
    }


def _next_invoice_number(counter: int, prefix: str) -> str:
    return f"{prefix}-{counter:04d}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Batch invoice generator from an Excel orders file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "excel_file",
        help="Path to the Excel orders file (.xlsx)",
    )
    parser.add_argument(
        "--output", "-o",
        default="output",
        metavar="DIR",
        help="Directory to save generated PDFs (default: ./output)",
    )
    parser.add_argument(
        "--send-email",
        action="store_true",
        help="Send each invoice by email after generating the PDF",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be processed without creating files or sending emails",
    )
    parser.add_argument(
        "--filter",
        metavar="EMAIL",
        help="Only process the specified customer email address",
    )
    parser.add_argument(
        "--invoice-start",
        type=int,
        default=1,
        metavar="N",
        help="Starting invoice counter (default: 1)",
    )
    parser.add_argument(
        "--tax-rate",
        type=float,
        default=None,
        metavar="RATE",
        help="Tax rate as a decimal, e.g. 0.20 for 20%% (overrides TAX_RATE env var)",
    )

    args = parser.parse_args()

    # ------------------------------------------------------------------ load
    print(f"\nLoading orders from: {args.excel_file}")
    try:
        customers = load_orders(args.excel_file)
    except FileNotFoundError as e:
        print(f"[error] {e}")
        sys.exit(1)
    except ValueError as e:
        print(f"[error] {e}")
        sys.exit(1)

    if not customers:
        print("[warning] No valid customer records found. Nothing to do.")
        sys.exit(0)

    # ----------------------------------------------------------- apply filter
    if args.filter:
        filter_key = args.filter.lower()
        if filter_key not in customers:
            print(f"[error] No orders found for email: {args.filter}")
            sys.exit(1)
        customers = {filter_key: customers[filter_key]}

    # ------------------------------------------------------- common settings
    company     = _get_company()
    tax_rate    = args.tax_rate if args.tax_rate is not None else float(os.getenv("TAX_RATE", "0.20"))
    currency    = os.getenv("CURRENCY_SYMBOL", "£")
    inv_prefix  = os.getenv("INVOICE_PREFIX",  "INV")
    output_dir  = Path(args.output)
    counter     = args.invoice_start

    # ------------------------------------------------------ summary / dry-run
    print(f"\n{'DRY RUN – ' if args.dry_run else ''}Processing {len(customers)} customer(s):\n")

    total_orders = sum(len(c.order_lines) for c in customers.values())
    print(f"  {'Customer':<35} {'Email':<35} {'Orders':>6}  {'Subtotal':>10}")
    print(f"  {'-'*35} {'-'*35} {'-'*6}  {'-'*10}")
    for data in customers.values():
        print(
            f"  {data.customer_name:<35} {data.email:<35} "
            f"{len(data.order_lines):>6}  "
            f"{currency}{data.subtotal:>9,.2f}"
        )
    print(f"\n  Total order lines : {total_orders}")
    print(f"  Output directory  : {output_dir.resolve()}")
    print(f"  Tax rate          : {int(tax_rate * 100)}%")
    print(f"  Send email        : {'yes' if args.send_email else 'no'}")

    if args.dry_run:
        print("\n[dry-run] No files generated.")
        sys.exit(0)

    # ------------------------------------------- generate + (optionally) send
    smtp = _get_smtp() if args.send_email else {}
    generated: list[tuple[str, Path]] = []
    failed:    list[str]              = []

    print("\nGenerating invoices…")
    for email, customer in customers.items():
        inv_number = _next_invoice_number(counter, inv_prefix)
        counter   += 1

        # -- PDF
        try:
            pdf_path = generate_invoice(
                customer=customer,
                invoice_number=inv_number,
                output_dir=output_dir,
                company=company,
                tax_rate=tax_rate,
                currency=currency,
            )
            generated.append((email, pdf_path))
            print(f"  [ok]  {inv_number}  {customer.customer_name:<35}  -> {pdf_path.name}")
        except Exception as exc:
            print(f"  [fail] {inv_number}  {customer.customer_name:<35}  PDF error: {exc}")
            failed.append(f"PDF: {customer.email} – {exc}")
            continue

        # -- Email
        if args.send_email:
            subtotal  = customer.subtotal
            total_due = round(subtotal + subtotal * tax_rate, 2)
            try:
                send_invoice(
                    to_email=customer.email,
                    customer_name=customer.customer_name,
                    invoice_number=inv_number,
                    pdf_path=pdf_path,
                    company=company,
                    smtp_host=smtp["host"],
                    smtp_port=smtp["port"],
                    smtp_user=smtp["user"],
                    smtp_password=smtp["password"],
                    currency=currency,
                    total_due=total_due,
                )
                print(f"         Email sent to {customer.email}")
            except Exception as exc:
                print(f"  [warn] Email to {customer.email} failed: {exc}")
                failed.append(f"Email: {customer.email} – {exc}")

    # ---------------------------------------------------------------- summary
    print(f"\n{'='*60}")
    print(f"  Invoices generated : {len(generated)}")
    print(f"  Failures           : {len(failed)}")
    if failed:
        print("\n  Failures:")
        for f in failed:
            print(f"    - {f}")
    print(f"  PDFs saved to      : {output_dir.resolve()}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
