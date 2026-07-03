from datetime import date, timedelta
from decimal import Decimal
from dateutil.relativedelta import relativedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from .models import db, RecurringTransaction, BudgetHeading, BankAccount, Transaction, FinancialYear, log_action

recurring_bp = Blueprint('recurring', __name__, url_prefix='/recurring')

FREQUENCIES = [
    ('monthly', 'Monthly'),
    ('quarterly', 'Quarterly (every 3 months)'),
    ('annual', 'Annual'),
    ('weekly', 'Weekly'),
]


def _advance_date(current_date, frequency):
    if frequency == 'monthly':
        return current_date + relativedelta(months=1)
    if frequency == 'quarterly':
        return current_date + relativedelta(months=3)
    if frequency == 'annual':
        return current_date + relativedelta(years=1)
    if frequency == 'weekly':
        return current_date + timedelta(weeks=1)
    return current_date + relativedelta(months=1)


@recurring_bp.route('/')
@login_required
def index():
    items = RecurringTransaction.query.filter_by(is_active=True).order_by(
        RecurringTransaction.next_due_date
    ).all()
    overdue = [i for i in items if i.is_overdue]
    upcoming = [i for i in items if not i.is_overdue]
    return render_template('recurring/index.html',
                           overdue=overdue, upcoming=upcoming)


@recurring_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if not current_user.can_edit:
        flash('Only the Clerk / RFO can add recurring transactions.', 'danger')
        return redirect(url_for('recurring.index'))

    headings = BudgetHeading.query.filter_by(is_active=True).order_by(BudgetHeading.sort_order).all()
    bank_accounts = BankAccount.query.filter_by(is_active=True).order_by(BankAccount.name).all()

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        txn_type = request.form.get('transaction_type', '')
        payee_payer = request.form.get('payee_payer', '').strip()
        description = request.form.get('description', '').strip()
        heading_id = request.form.get('budget_heading_id', '')
        bank_account_id = request.form.get('bank_account_id', '') or None
        net_str = request.form.get('net_amount', '').strip()
        vat_str = request.form.get('vat_amount', '0').strip() or '0'
        frequency = request.form.get('frequency', 'monthly')
        next_due_str = request.form.get('next_due_date', '')

        errors = []
        if not name:
            errors.append('Name is required.')
        if txn_type not in ('receipt', 'payment'):
            errors.append('Please select receipt or payment.')
        if not payee_payer:
            errors.append('Payee / Payer is required.')
        if not heading_id.isdigit():
            errors.append('Budget heading is required.')
        try:
            net_amount = Decimal(net_str)
            if net_amount <= 0:
                errors.append('Amount must be positive.')
        except Exception:
            errors.append('Invalid amount.')
            net_amount = Decimal('0')
        try:
            next_due = date.fromisoformat(next_due_str)
        except (ValueError, AttributeError):
            errors.append('Invalid next due date.')
            next_due = date.today()

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('recurring/add.html', headings=headings,
                                   bank_accounts=bank_accounts, frequencies=FREQUENCIES, form=request.form)

        rec = RecurringTransaction(
            name=name,
            transaction_type=txn_type,
            payee_payer=payee_payer,
            description=description,
            budget_heading_id=int(heading_id),
            bank_account_id=int(bank_account_id) if bank_account_id and bank_account_id.isdigit() else None,
            net_amount=net_amount,
            vat_amount=Decimal(vat_str),
            vat_reclaimable=request.form.get('vat_reclaimable') == '1',
            frequency=frequency,
            next_due_date=next_due,
            created_by_id=current_user.id,
        )
        db.session.add(rec)
        db.session.flush()
        log_action(current_user.id, 'recurring', 'create',
                   f'Added recurring {txn_type}: {name} — £{net_amount:,.2f} {frequency}',
                   entity_id=rec.id)
        db.session.commit()
        flash(f'Recurring transaction "{name}" added.', 'success')
        return redirect(url_for('recurring.index'))

    return render_template('recurring/add.html', headings=headings,
                           bank_accounts=bank_accounts, frequencies=FREQUENCIES,
                           form={'next_due_date': str(date.today())})


@recurring_bp.route('/<int:rec_id>/post', methods=['POST'])
@login_required
def post(rec_id):
    """Post a recurring transaction to the cashbook."""
    if not current_user.can_edit:
        flash('Access denied.', 'danger')
        return redirect(url_for('recurring.index'))

    rec = db.get_or_404(RecurringTransaction, rec_id)
    fy = FinancialYear.query.filter_by(is_current=True).first()
    if not fy:
        flash('No current financial year configured.', 'warning')
        return redirect(url_for('recurring.index'))

    post_date = rec.next_due_date
    if post_date < fy.start_date or post_date > fy.end_date:
        flash(f'Due date {post_date} is outside the current financial year ({fy.label}).', 'danger')
        return redirect(url_for('recurring.index'))

    # Auto-generate reference
    count = Transaction.query.filter_by(financial_year_id=fy.id).count() + 1
    ref = f'REC-{count:04d}'

    txn = Transaction(
        financial_year_id=fy.id,
        bank_account_id=rec.bank_account_id,
        date=post_date,
        reference=ref,
        payee_payer=rec.payee_payer,
        description=rec.description,
        budget_heading_id=rec.budget_heading_id,
        transaction_type=rec.transaction_type,
        net_amount=rec.net_amount,
        vat_amount=rec.vat_amount,
        vat_reclaimable=rec.vat_reclaimable,
        created_by_id=current_user.id,
    )
    db.session.add(txn)

    rec.next_due_date = _advance_date(rec.next_due_date, rec.frequency)
    log_action(current_user.id, 'recurring', 'post',
               f'Posted recurring transaction "{rec.name}" as {ref}',
               entity_id=rec.id)
    db.session.commit()
    flash(f'Transaction {ref} posted to cashbook. Next due: {rec.next_due_date.strftime("%d/%m/%Y")}.', 'success')
    return redirect(url_for('cashbook.index'))


@recurring_bp.route('/<int:rec_id>/deactivate', methods=['POST'])
@login_required
def deactivate(rec_id):
    if not current_user.can_edit:
        flash('Access denied.', 'danger')
        return redirect(url_for('recurring.index'))
    rec = db.get_or_404(RecurringTransaction, rec_id)
    rec.is_active = False
    log_action(current_user.id, 'recurring', 'deactivate',
               f'Deactivated recurring transaction: {rec.name}', entity_id=rec.id)
    db.session.commit()
    flash(f'"{rec.name}" deactivated.', 'success')
    return redirect(url_for('recurring.index'))
