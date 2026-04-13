"""
excel_reader.py
Parses an orders Excel file and groups rows by customer for invoice generation.

Expected columns (case-insensitive, whitespace-stripped):
  Order Date | Order Number | Customer Name | Email | Item Description | Quantity | Unit Price
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

import pandas as pd


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class OrderLine:
    order_date: str
    order_number: str
    description: str
    quantity: float
    unit_price: float

    @property
    def line_total(self) -> float:
        return round(self.quantity * self.unit_price, 2)


@dataclass
class CustomerInvoiceData:
    customer_name: str
    email: str
    order_lines: List[OrderLine] = field(default_factory=list)

    @property
    def subtotal(self) -> float:
        return round(sum(line.line_total for line in self.order_lines), 2)


# ---------------------------------------------------------------------------
# Column normalisation helpers
# ---------------------------------------------------------------------------

# Flexible column name aliases (normalised key -> list of accepted raw names)
_COLUMN_ALIASES: Dict[str, List[str]] = {
    "order_date":    ["order date", "date", "order_date"],
    "order_number":  ["order number", "order no", "order#", "order_number", "order_no"],
    "customer_name": ["customer name", "customer", "name", "client name", "client", "customer_name"],
    "email":         ["email", "email address", "e-mail", "e_mail", "emailaddress"],
    "description":   ["item description", "description", "product", "product description",
                      "purchase details", "item", "details"],
    "quantity":      ["quantity", "qty", "units", "amount"],
    "unit_price":    ["unit price", "price", "unit_price", "cost", "rate", "unit cost"],
}


def _normalise_col(raw: str) -> str:
    """Lower-case, strip, collapse whitespace."""
    return re.sub(r"\s+", " ", raw.strip().lower())


def _map_columns(df_columns: List[str]) -> Dict[str, str]:
    """
    Return {canonical_key: actual_df_column} for every required column.
    Raises ValueError if any required column cannot be matched.
    """
    normalised = {_normalise_col(c): c for c in df_columns}
    mapping: Dict[str, str] = {}

    for key, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in normalised:
                mapping[key] = normalised[alias]
                break
        if key not in mapping:
            raise ValueError(
                f"Cannot find a column for '{key}'. "
                f"Expected one of: {aliases}. "
                f"Found columns: {list(df_columns)}"
            )
    return mapping


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_orders(filepath: str | Path) -> Dict[str, CustomerInvoiceData]:
    """
    Read an Excel file and return a dict keyed by lower-cased email address.
    Each value is a CustomerInvoiceData aggregating all order lines for that customer.

    Args:
        filepath: Path to the .xlsx / .xls file.

    Returns:
        Dict mapping email -> CustomerInvoiceData.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If required columns are missing or data is malformed.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Orders file not found: {path}")

    df = pd.read_excel(path, dtype=str)          # read everything as string first
    df.columns = [str(c) for c in df.columns]    # ensure column names are strings

    col = _map_columns(list(df.columns))          # {canonical -> raw column name}

    # Drop completely empty rows
    df.dropna(how="all", inplace=True)

    customers: Dict[str, CustomerInvoiceData] = {}
    errors: List[str] = []

    for row_idx, row in df.iterrows():
        row_num = int(row_idx) + 2  # 1-based spreadsheet row (header = row 1)

        # --- required fields ---
        email_raw = str(row[col["email"]]).strip()
        if not email_raw or email_raw.lower() == "nan":
            errors.append(f"Row {row_num}: missing email — skipped.")
            continue

        email = email_raw.lower()
        customer_name = str(row[col["customer_name"]]).strip()

        order_date = str(row[col["order_date"]]).strip()
        order_number = str(row[col["order_number"]]).strip()
        description = str(row[col["description"]]).strip()

        # --- numeric fields ---
        try:
            quantity = float(str(row[col["quantity"]]).replace(",", "").strip())
        except (ValueError, TypeError):
            errors.append(f"Row {row_num}: invalid quantity '{row[col['quantity']]}' — skipped.")
            continue

        try:
            unit_price = float(
                str(row[col["unit_price"]])
                .replace(",", "")
                .replace("£", "")
                .replace("$", "")
                .replace("€", "")
                .strip()
            )
        except (ValueError, TypeError):
            errors.append(f"Row {row_num}: invalid unit price '{row[col['unit_price']]}' — skipped.")
            continue

        # --- accumulate ---
        if email not in customers:
            customers[email] = CustomerInvoiceData(
                customer_name=customer_name,
                email=email_raw,
            )

        customers[email].order_lines.append(
            OrderLine(
                order_date=order_date,
                order_number=order_number,
                description=description,
                quantity=quantity,
                unit_price=unit_price,
            )
        )

    if errors:
        print("\n[excel_reader] Warnings:")
        for e in errors:
            print(f"  {e}")

    return customers
