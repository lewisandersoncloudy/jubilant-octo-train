from decimal import Decimal
from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required
from .models import FinancialYear, Transaction

vat_bp = Blueprint('vat', __name__, url_prefix='/vat')


@vat_bp.route('/')
@login_required
def index():
    fy = FinancialYear.query.filter_by(is_current=True).first()
    if not fy:
        flash('No current financial year configured.', 'warning')
        return redirect(url_for('dashboard'))

    # All active transactions with VAT
    vat_txns = Transaction.query.filter(
        Transaction.financial_year_id == fy.id,
        Transaction.is_void == False,
        Transaction.vat_amount > 0,
    ).order_by(Transaction.date, Transaction.id).all()

    receipts_vat = sum(
        Decimal(str(t.vat_amount)) for t in vat_txns if t.transaction_type == 'receipt'
    )
    payments_vat_total = sum(
        Decimal(str(t.vat_amount)) for t in vat_txns if t.transaction_type == 'payment'
    )
    payments_vat_reclaimable = sum(
        Decimal(str(t.vat_amount))
        for t in vat_txns
        if t.transaction_type == 'payment' and t.vat_reclaimable
    )
    net_reclaimable = payments_vat_reclaimable - receipts_vat

    return render_template('vat/index.html',
                           fy=fy,
                           vat_txns=vat_txns,
                           receipts_vat=receipts_vat,
                           payments_vat_total=payments_vat_total,
                           payments_vat_reclaimable=payments_vat_reclaimable,
                           net_reclaimable=net_reclaimable)
