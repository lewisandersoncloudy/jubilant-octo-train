"""
AGAR Helper — maps cashbook totals to AGAR Section 2 boxes and flags inconsistencies.
Does NOT generate or submit the AGAR form itself.
"""
from decimal import Decimal
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from .models import db, FinancialYear, Transaction, Reserve, BankReconciliation

agar_bp = Blueprint('agar', __name__, url_prefix='/agar')


def _compute_agar(fy):
    """Compute AGAR Section 2 box values from the cashbook."""
    active = Transaction.query.filter_by(financial_year_id=fy.id, is_void=False).all()

    receipts_gross = sum(
        Decimal(str(t.net_amount)) + Decimal(str(t.vat_amount))
        for t in active if t.transaction_type == 'receipt'
    )
    payments_gross = sum(
        Decimal(str(t.net_amount)) + Decimal(str(t.vat_amount))
        for t in active if t.transaction_type == 'payment'
    )

    # Box 1 – Balances brought forward: use opening balance of first reconciliation
    first_recon = BankReconciliation.query.filter_by(
        financial_year_id=fy.id
    ).order_by(BankReconciliation.year, BankReconciliation.month).first()
    box1 = Decimal(str(first_recon.opening_balance)) if first_recon else Decimal('0')

    # Box 2 – Annual precept
    from .models import BudgetHeading
    precept_heading = BudgetHeading.query.filter_by(name='Precept').first()
    box2 = Decimal('0')
    if precept_heading:
        box2 = sum(
            Decimal(str(t.net_amount))
            for t in active
            if t.transaction_type == 'receipt' and t.budget_heading_id == precept_heading.id
        )

    # Box 3 – Total other receipts
    box3 = receipts_gross - box2

    # Box 4 – Staff costs (clerk salary heading)
    clerk_heading = BudgetHeading.query.filter_by(name='Clerk Salary').first()
    box4 = Decimal('0')
    if clerk_heading:
        box4 = sum(
            Decimal(str(t.net_amount))
            for t in active
            if t.transaction_type == 'payment' and t.budget_heading_id == clerk_heading.id
        )

    # Box 5 – Loan repayments (not modelled — show 0)
    box5 = Decimal('0')

    # Box 6 – All other payments
    box6 = payments_gross - box4 - box5

    # Box 7 – Balances carried forward: box1 + box2 + box3 - box4 - box5 - box6
    box7 = box1 + box2 + box3 - box4 - box5 - box6

    # Box 8 – Total value of cash and short-term investments: from latest reconciliation
    last_recon = BankReconciliation.query.filter_by(
        financial_year_id=fy.id, is_complete=True
    ).order_by(BankReconciliation.year.desc(), BankReconciliation.month.desc()).first()
    box8 = Decimal(str(last_recon.closing_balance)) if last_recon else Decimal('0')

    # Reserve total
    reserves = Reserve.query.filter_by(is_active=True).all()
    total_reserves = sum(r.balance for r in reserves)

    checks = []
    if abs(box7 - box8) > Decimal('0.01'):
        checks.append({
            'level': 'warning',
            'message': (
                f'Box 7 (£{box7:,.2f}) does not equal Box 8 (£{box8:,.2f}). '
                f'Difference: £{box8 - box7:,.2f}. '
                'This may indicate unreconciled items or an error.'
            ),
        })
    if box7 < 0:
        checks.append({
            'level': 'danger',
            'message': 'Box 7 is negative — this suggests the council has spent more than it received.',
        })

    return {
        'box1': box1, 'box2': box2, 'box3': box3,
        'box4': box4, 'box5': box5, 'box6': box6,
        'box7': box7, 'box8': box8,
        'receipts_gross': receipts_gross,
        'payments_gross': payments_gross,
        'total_reserves': total_reserves,
        'checks': checks,
    }


@agar_bp.route('/')
@login_required
def index():
    fy = FinancialYear.query.filter_by(is_current=True).first()
    if not fy:
        flash('No current financial year configured.', 'warning')
        return redirect(url_for('dashboard'))

    data = _compute_agar(fy)
    return render_template('agar/index.html', fy=fy, **data)
