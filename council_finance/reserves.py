from datetime import date
from decimal import Decimal
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from .models import db, Reserve, ReserveTransfer, log_action

reserves_bp = Blueprint('reserves', __name__, url_prefix='/reserves')


@reserves_bp.route('/')
@login_required
def index():
    reserves = Reserve.query.filter_by(is_active=True).order_by(
        Reserve.is_general.desc(), Reserve.name
    ).all()
    total = sum(r.balance for r in reserves)
    return render_template('reserves/index.html', reserves=reserves, total=total)


@reserves_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add_reserve():
    if not current_user.can_edit:
        flash('Only the Clerk / RFO can add reserves.', 'danger')
        return redirect(url_for('reserves.index'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        if not name:
            flash('Reserve name is required.', 'danger')
            return render_template('reserves/add_reserve.html')

        if Reserve.query.filter_by(name=name).first():
            flash('A reserve with that name already exists.', 'danger')
            return render_template('reserves/add_reserve.html')

        reserve = Reserve(name=name, description=description)
        db.session.add(reserve)
        db.session.flush()
        log_action(current_user.id, 'reserve', 'create',
                   f'Created reserve: {name}', entity_id=reserve.id)
        db.session.commit()
        flash(f'Reserve "{name}" created.', 'success')
        return redirect(url_for('reserves.index'))

    return render_template('reserves/add_reserve.html')


@reserves_bp.route('/<int:reserve_id>/transfer', methods=['GET', 'POST'])
@login_required
def transfer(reserve_id):
    if not current_user.can_edit:
        flash('Only the Clerk / RFO can record transfers.', 'danger')
        return redirect(url_for('reserves.index'))

    reserve = db.get_or_404(Reserve, reserve_id)

    if request.method == 'POST':
        date_str = request.form.get('date', '').strip()
        direction = request.form.get('direction', '')  # 'in' or 'out'
        amount_str = request.form.get('amount', '').strip()
        reason = request.form.get('reason', '').strip()
        minute_ref = request.form.get('minute_reference', '').strip()

        errors = []
        if not date_str:
            errors.append('Date is required.')
        if direction not in ('in', 'out'):
            errors.append('Please select In or Out.')
        if not reason:
            errors.append('Reason is required.')
        try:
            amount = Decimal(amount_str)
            if amount <= 0:
                errors.append('Amount must be greater than zero.')
        except Exception:
            errors.append('Amount must be a valid number.')
            amount = Decimal('0')

        try:
            txn_date = date.fromisoformat(date_str)
        except (ValueError, AttributeError):
            errors.append('Invalid date.')
            txn_date = date.today()

        if direction == 'out' and not errors:
            if reserve.balance - amount < 0:
                errors.append(
                    f'Cannot withdraw £{amount:,.2f} — reserve balance is only '
                    f'£{reserve.balance:,.2f}.'
                )

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('reserves/transfer.html', reserve=reserve, form=request.form)

        signed_amount = amount if direction == 'in' else -amount
        t = ReserveTransfer(
            reserve_id=reserve.id,
            date=txn_date,
            amount=signed_amount,
            reason=reason,
            minute_reference=minute_ref if minute_ref else None,
            created_by_id=current_user.id,
        )
        db.session.add(t)
        db.session.flush()
        action_word = 'Added to' if direction == 'in' else 'Withdrawn from'
        log_action(current_user.id, 'reserve_transfer', 'create',
                   f'{action_word} reserve "{reserve.name}": £{amount:,.2f} — {reason}',
                   entity_id=t.id, reason=reason)
        db.session.commit()
        flash(f'Transfer of £{amount:,.2f} recorded for "{reserve.name}".', 'success')
        return redirect(url_for('reserves.index'))

    return render_template('reserves/transfer.html', reserve=reserve,
                           form={'date': str(date.today())})


@reserves_bp.route('/<int:reserve_id>')
@login_required
def view(reserve_id):
    reserve = db.get_or_404(Reserve, reserve_id)
    transfers = reserve.transfers.order_by(ReserveTransfer.date.desc()).all()
    running = []
    balance = Decimal('0')
    for t in reversed(transfers):
        balance += Decimal(str(t.amount))
        running.append({'transfer': t, 'balance': balance})
    running.reverse()
    return render_template('reserves/view.html', reserve=reserve,
                           transfers=running, current_balance=reserve.balance)
