from datetime import date
from decimal import Decimal
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from .models import db, Grant, log_action

grants_bp = Blueprint('grants', __name__, url_prefix='/grants')


@grants_bp.route('/')
@login_required
def index():
    grants = Grant.query.order_by(Grant.is_active.desc(), Grant.award_date.desc()).all()
    return render_template('grants/index.html', grants=grants)


@grants_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if not current_user.can_edit:
        flash('Only the Clerk / RFO can add grants.', 'danger')
        return redirect(url_for('grants.index'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        grantor = request.form.get('grantor', '').strip()
        grant_type = request.form.get('grant_type', 'received')
        amount_str = request.form.get('awarded_amount', '').strip()
        award_date_str = request.form.get('award_date', '').strip()
        deadline_str = request.form.get('expenditure_deadline', '').strip()
        conditions = request.form.get('conditions', '').strip()
        purpose = request.form.get('purpose', '').strip()

        errors = []
        if not name:
            errors.append('Grant name is required.')
        if not grantor:
            errors.append('Grantor / Funder is required.')
        if grant_type not in ('received', 'awarded'):
            errors.append('Invalid grant type.')
        try:
            amount = Decimal(amount_str)
            if amount <= 0:
                errors.append('Amount must be positive.')
        except Exception:
            errors.append('Invalid amount.')
            amount = Decimal('0')

        award_date = None
        if award_date_str:
            try:
                award_date = date.fromisoformat(award_date_str)
            except ValueError:
                errors.append('Invalid award date.')

        deadline = None
        if deadline_str:
            try:
                deadline = date.fromisoformat(deadline_str)
            except ValueError:
                errors.append('Invalid expenditure deadline.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('grants/add.html', form=request.form)

        grant = Grant(
            name=name,
            grantor=grantor,
            grant_type=grant_type,
            awarded_amount=amount,
            award_date=award_date,
            expenditure_deadline=deadline,
            conditions=conditions or None,
            purpose=purpose or None,
            created_by_id=current_user.id,
        )
        db.session.add(grant)
        db.session.flush()
        log_action(current_user.id, 'grant', 'create',
                   f'Added grant: {name} from {grantor} — £{amount:,.2f}',
                   entity_id=grant.id)
        db.session.commit()
        flash(f'Grant "{name}" added.', 'success')
        return redirect(url_for('grants.index'))

    return render_template('grants/add.html', form={})


@grants_bp.route('/<int:grant_id>')
@login_required
def view(grant_id):
    grant = db.get_or_404(Grant, grant_id)
    txns = grant.transactions.filter_by(is_void=False).order_by('date').all()
    return render_template('grants/view.html', grant=grant, txns=txns)
