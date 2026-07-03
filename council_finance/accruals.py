"""Accruals and prepayments — Income & Expenditure basis only."""
from datetime import date, datetime
from decimal import Decimal
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from .models import db, Accrual, BudgetHeading, FinancialYear, CouncilSettings, log_action

accruals_bp = Blueprint('accruals', __name__, url_prefix='/accruals')

ACCRUAL_TYPES = [
    ('accrued_income', 'Accrued Income — income earned but not yet received'),
    ('debtor', 'Debtor — amount owed to the council'),
    ('prepayment', 'Prepayment — payment made for next year\'s services'),
    ('accrued_expenditure', 'Accrued Expenditure — cost incurred but not yet paid'),
    ('creditor', 'Creditor — amount owed by the council'),
]


@accruals_bp.route('/')
@login_required
def index():
    settings = CouncilSettings.query.first()
    if settings and not settings.is_ie:
        flash('Accruals are only used under Income & Expenditure accounting. '
              'Your council uses Receipts & Payments basis.', 'info')
        return redirect(url_for('dashboard'))

    fy = FinancialYear.query.filter_by(is_current=True).first()
    if not fy:
        flash('No current financial year configured.', 'warning')
        return redirect(url_for('dashboard'))

    active = Accrual.query.filter_by(
        financial_year_id=fy.id, is_reversed=False
    ).order_by(Accrual.accrual_type, Accrual.date).all()

    reversed_items = Accrual.query.filter_by(
        financial_year_id=fy.id, is_reversed=True
    ).order_by(Accrual.reversed_at.desc()).all()

    # Totals by type
    assets_total = sum(Decimal(str(a.amount)) for a in active if a.is_asset)
    liabilities_total = sum(Decimal(str(a.amount)) for a in active if not a.is_asset)

    return render_template('accruals/index.html', fy=fy,
                           active=active, reversed_items=reversed_items,
                           assets_total=assets_total, liabilities_total=liabilities_total)


@accruals_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if not current_user.can_edit:
        flash('Only the Clerk / RFO can add accruals.', 'danger')
        return redirect(url_for('accruals.index'))

    fy = FinancialYear.query.filter_by(is_current=True).first()
    headings = BudgetHeading.query.filter_by(is_active=True).order_by(BudgetHeading.sort_order).all()

    if request.method == 'POST':
        accrual_type = request.form.get('accrual_type', '')
        date_str = request.form.get('date', '')
        amount_str = request.form.get('amount', '').strip()
        description = request.form.get('description', '').strip()
        counterparty = request.form.get('counterparty', '').strip()
        heading_id = request.form.get('budget_heading_id', '')

        errors = []
        valid_types = [k for k, _ in ACCRUAL_TYPES]
        if accrual_type not in valid_types:
            errors.append('Please select an accrual type.')
        if not description:
            errors.append('Description is required.')
        try:
            amount = Decimal(amount_str)
            if amount <= 0:
                errors.append('Amount must be positive.')
        except Exception:
            errors.append('Invalid amount.')
            amount = Decimal('0')
        try:
            accrual_date = date.fromisoformat(date_str)
        except (ValueError, AttributeError):
            errors.append('Invalid date.')
            accrual_date = date.today()

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('accruals/add.html', fy=fy, headings=headings,
                                   accrual_types=ACCRUAL_TYPES, form=request.form)

        accrual = Accrual(
            financial_year_id=fy.id,
            accrual_type=accrual_type,
            budget_heading_id=int(heading_id) if heading_id.isdigit() else None,
            date=accrual_date,
            amount=amount,
            description=description,
            counterparty=counterparty or None,
            created_by_id=current_user.id,
        )
        db.session.add(accrual)
        db.session.flush()
        log_action(current_user.id, 'accrual', 'create',
                   f'Added {accrual.type_label}: {description} — £{amount:,.2f}',
                   entity_id=accrual.id)
        db.session.commit()
        flash(f'{accrual.type_label} of £{amount:,.2f} recorded.', 'success')
        return redirect(url_for('accruals.index'))

    return render_template('accruals/add.html', fy=fy, headings=headings,
                           accrual_types=ACCRUAL_TYPES, form={})


@accruals_bp.route('/<int:accrual_id>/reverse', methods=['POST'])
@login_required
def reverse(accrual_id):
    if not current_user.can_edit:
        flash('Access denied.', 'danger')
        return redirect(url_for('accruals.index'))

    accrual = db.get_or_404(Accrual, accrual_id)
    if accrual.is_reversed:
        flash('Already reversed.', 'warning')
        return redirect(url_for('accruals.index'))

    accrual.is_reversed = True
    accrual.reversed_at = datetime.utcnow()
    accrual.reversed_by_id = current_user.id
    log_action(current_user.id, 'accrual', 'reverse',
               f'Reversed {accrual.type_label}: {accrual.description}',
               entity_id=accrual.id)
    db.session.commit()
    flash('Accrual reversed.', 'success')
    return redirect(url_for('accruals.index'))
