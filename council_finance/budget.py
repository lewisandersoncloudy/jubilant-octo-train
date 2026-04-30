from datetime import datetime
from decimal import Decimal
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from .models import db, Budget, BudgetHeading, FinancialYear, Transaction, log_action

budget_bp = Blueprint('budget', __name__, url_prefix='/budget')

RAG_AMBER_THRESHOLD = Decimal('0.75')
RAG_RED_THRESHOLD = Decimal('0.95')


def _rag_status(spent, budget_amt):
    """Return 'green', 'amber', or 'red' based on spend ratio."""
    if budget_amt <= 0:
        return 'grey'
    ratio = spent / budget_amt
    if ratio >= RAG_RED_THRESHOLD:
        return 'red'
    if ratio >= RAG_AMBER_THRESHOLD:
        return 'amber'
    return 'green'


@budget_bp.route('/')
@login_required
def index():
    fy = FinancialYear.query.filter_by(is_current=True).first()
    if not fy:
        flash('No current financial year configured.', 'warning')
        return redirect(url_for('dashboard'))

    headings = BudgetHeading.query.filter_by(is_active=True).order_by(BudgetHeading.sort_order).all()
    rows = []
    total_budget_receipts = Decimal('0')
    total_spent_receipts = Decimal('0')
    total_budget_payments = Decimal('0')
    total_spent_payments = Decimal('0')

    for h in headings:
        budget_obj = Budget.query.filter_by(
            financial_year_id=fy.id, budget_heading_id=h.id
        ).first()
        budget_amt = Decimal(str(budget_obj.effective_amount)) if budget_obj else Decimal('0')

        spent = sum(
            Decimal(str(t.net_amount))
            for t in Transaction.query.filter_by(
                financial_year_id=fy.id,
                budget_heading_id=h.id,
                is_void=False,
            ).all()
        )

        remaining = budget_amt - spent
        rag = _rag_status(spent, budget_amt)

        rows.append({
            'heading': h,
            'budget': budget_amt,
            'spent': spent,
            'remaining': remaining,
            'rag': rag,
            'budget_obj': budget_obj,
        })

        if h.category == 'receipts':
            total_budget_receipts += budget_amt
            total_spent_receipts += spent
        else:
            total_budget_payments += budget_amt
            total_spent_payments += spent

    return render_template('budget/index.html', fy=fy, rows=rows,
                           total_budget_receipts=total_budget_receipts,
                           total_spent_receipts=total_spent_receipts,
                           total_budget_payments=total_budget_payments,
                           total_spent_payments=total_spent_payments)


@budget_bp.route('/setup', methods=['GET', 'POST'])
@login_required
def setup():
    if not current_user.can_edit:
        flash('Only the Clerk / RFO can set budgets.', 'danger')
        return redirect(url_for('budget.index'))

    fy = FinancialYear.query.filter_by(is_current=True).first()
    if not fy:
        flash('No current financial year configured.', 'warning')
        return redirect(url_for('dashboard'))

    if fy.budget_locked:
        flash('The budget for this year has been approved and is locked. '
              'Use "Adjust" to make a mid-year adjustment with a note.', 'info')
        return redirect(url_for('budget.index'))

    headings = BudgetHeading.query.filter_by(is_active=True).order_by(BudgetHeading.sort_order).all()

    if request.method == 'POST':
        errors = []
        amounts = {}
        for h in headings:
            val_str = request.form.get(f'amount_{h.id}', '0').strip() or '0'
            try:
                amt = Decimal(val_str)
                if amt < 0:
                    errors.append(f'{h.name}: amount cannot be negative.')
                amounts[h.id] = amt
            except Exception:
                errors.append(f'{h.name}: invalid amount.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('budget/setup.html', fy=fy, headings=headings,
                                   existing={})

        for h in headings:
            budget_obj = Budget.query.filter_by(
                financial_year_id=fy.id, budget_heading_id=h.id
            ).first()
            if budget_obj:
                budget_obj.amount = amounts[h.id]
            else:
                db.session.add(Budget(
                    financial_year_id=fy.id,
                    budget_heading_id=h.id,
                    amount=amounts[h.id],
                ))

        log_action(current_user.id, 'budget', 'setup',
                   f'Set annual budget for {fy.label}')
        db.session.commit()
        flash('Budget saved. You can edit it again until you approve it.', 'success')
        return redirect(url_for('budget.index'))

    existing = {
        b.budget_heading_id: b.amount
        for b in Budget.query.filter_by(financial_year_id=fy.id).all()
    }
    return render_template('budget/setup.html', fy=fy, headings=headings, existing=existing)


@budget_bp.route('/approve', methods=['POST'])
@login_required
def approve():
    if not current_user.can_edit:
        flash('Access denied.', 'danger')
        return redirect(url_for('budget.index'))

    fy = FinancialYear.query.filter_by(is_current=True).first()
    if not fy or fy.budget_locked:
        flash('Budget already approved or no financial year configured.', 'warning')
        return redirect(url_for('budget.index'))

    fy.budget_approved_at = datetime.utcnow()
    fy.budget_approved_by_id = current_user.id
    log_action(current_user.id, 'budget', 'approve',
               f'Approved and locked budget for {fy.label}')
    db.session.commit()
    flash(f'Budget for {fy.label} approved and locked.', 'success')
    return redirect(url_for('budget.index'))


@budget_bp.route('/adjust/<int:budget_id>', methods=['GET', 'POST'])
@login_required
def adjust(budget_id):
    if not current_user.can_edit:
        flash('Access denied.', 'danger')
        return redirect(url_for('budget.index'))

    budget_obj = db.get_or_404(Budget, budget_id)
    fy = budget_obj.financial_year

    if not fy.budget_locked:
        flash('Budget is not yet approved — use the setup page to edit amounts.', 'info')
        return redirect(url_for('budget.setup'))

    if request.method == 'POST':
        new_amt_str = request.form.get('adjusted_amount', '').strip()
        note = request.form.get('adjustment_note', '').strip()
        if not note:
            flash('An adjustment note is required.', 'danger')
            return render_template('budget/adjust.html', budget_obj=budget_obj, fy=fy)
        try:
            new_amt = Decimal(new_amt_str)
            if new_amt < 0:
                raise ValueError
        except Exception:
            flash('Please enter a valid positive amount.', 'danger')
            return render_template('budget/adjust.html', budget_obj=budget_obj, fy=fy)

        before = {'amount': str(budget_obj.effective_amount)}
        budget_obj.adjusted_amount = new_amt
        budget_obj.adjustment_note = note
        budget_obj.adjusted_at = datetime.utcnow()
        budget_obj.adjusted_by_id = current_user.id
        log_action(current_user.id, 'budget', 'adjust',
                   f'Adjusted budget for {budget_obj.heading.name} in {fy.label}',
                   entity_id=budget_obj.id, reason=note,
                   before=before, after={'amount': str(new_amt)})
        db.session.commit()
        flash('Budget adjustment recorded.', 'success')
        return redirect(url_for('budget.index'))

    return render_template('budget/adjust.html', budget_obj=budget_obj, fy=fy)


@budget_bp.route('/headings')
@login_required
def headings():
    if not current_user.can_edit:
        flash('Access denied.', 'danger')
        return redirect(url_for('budget.index'))
    all_headings = BudgetHeading.query.order_by(BudgetHeading.sort_order).all()
    return render_template('budget/headings.html', headings=all_headings)


@budget_bp.route('/headings/add', methods=['POST'])
@login_required
def add_heading():
    if not current_user.can_edit:
        flash('Access denied.', 'danger')
        return redirect(url_for('budget.headings'))

    name = request.form.get('name', '').strip()
    category = request.form.get('category', '')
    if not name or category not in ('receipts', 'payments'):
        flash('Name and category are required.', 'danger')
        return redirect(url_for('budget.headings'))

    if BudgetHeading.query.filter_by(name=name, category=category).first():
        flash('A heading with that name already exists in that category.', 'danger')
        return redirect(url_for('budget.headings'))

    max_order = db.session.query(db.func.max(BudgetHeading.sort_order)).scalar() or 0
    heading = BudgetHeading(name=name, category=category, sort_order=max_order + 1)
    db.session.add(heading)
    log_action(current_user.id, 'budget_heading', 'create',
               f'Added budget heading: {name} ({category})')
    db.session.commit()
    flash(f'Heading "{name}" added.', 'success')
    return redirect(url_for('budget.headings'))
