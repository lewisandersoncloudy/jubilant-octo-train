from datetime import date
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from .models import db, User, log_action

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


def clerk_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.can_edit:
            flash('Only the Clerk / RFO can perform this action.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password) and user.has_access:
            login_user(user, remember=False)
            return redirect(url_for('dashboard'))
        flash('Invalid email or password, or your access has expired.', 'danger')
    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))


@auth_bp.route('/users')
@login_required
def users():
    if not current_user.can_edit:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    all_users = User.query.order_by(User.name).all()
    return render_template('auth/users.html', users=all_users)


@auth_bp.route('/users/add', methods=['GET', 'POST'])
@login_required
def add_user():
    if not current_user.can_edit:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        name = request.form.get('name', '').strip()
        role = request.form.get('role', 'councillor')
        password = request.form.get('password', '')
        auditor_until_str = request.form.get('auditor_access_until', '')

        if not email or not name or not password:
            flash('Email, name, and password are required.', 'danger')
            return render_template('auth/add_user.html')

        if User.query.filter_by(email=email).first():
            flash('A user with that email already exists.', 'danger')
            return render_template('auth/add_user.html')

        if role not in ('clerk', 'councillor', 'auditor'):
            flash('Invalid role.', 'danger')
            return render_template('auth/add_user.html')

        auditor_until = None
        if role == 'auditor' and auditor_until_str:
            try:
                auditor_until = date.fromisoformat(auditor_until_str)
            except ValueError:
                flash('Invalid auditor access date.', 'danger')
                return render_template('auth/add_user.html')

        user = User(email=email, name=name, role=role, auditor_access_until=auditor_until)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        log_action(current_user.id, 'user', 'create',
                   f'Created user {name} ({email}) with role {role}', entity_id=user.id)
        db.session.commit()
        flash(f'User {name} created successfully.', 'success')
        return redirect(url_for('auth.users'))

    return render_template('auth/add_user.html')


@auth_bp.route('/users/<int:user_id>/deactivate', methods=['POST'])
@login_required
def deactivate_user(user_id):
    if not current_user.can_edit:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        flash('You cannot deactivate your own account.', 'danger')
        return redirect(url_for('auth.users'))
    user.is_active = False
    log_action(current_user.id, 'user', 'deactivate',
               f'Deactivated user {user.name}', entity_id=user.id)
    db.session.commit()
    flash(f'{user.name} has been deactivated.', 'success')
    return redirect(url_for('auth.users'))


@auth_bp.route('/users/<int:user_id>/reactivate', methods=['POST'])
@login_required
def reactivate_user(user_id):
    if not current_user.can_edit:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    user = db.get_or_404(User, user_id)
    user.is_active = True
    log_action(current_user.id, 'user', 'reactivate',
               f'Reactivated user {user.name}', entity_id=user.id)
    db.session.commit()
    flash(f'{user.name} has been reactivated.', 'success')
    return redirect(url_for('auth.users'))


@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_pw = request.form.get('current_password', '')
        new_pw = request.form.get('new_password', '')
        confirm_pw = request.form.get('confirm_password', '')
        if not current_user.check_password(current_pw):
            flash('Current password is incorrect.', 'danger')
        elif len(new_pw) < 8:
            flash('New password must be at least 8 characters.', 'danger')
        elif new_pw != confirm_pw:
            flash('Passwords do not match.', 'danger')
        else:
            current_user.set_password(new_pw)
            log_action(current_user.id, 'user', 'password_change',
                       'Changed own password', entity_id=current_user.id)
            db.session.commit()
            flash('Password changed successfully.', 'success')
            return redirect(url_for('dashboard'))
    return render_template('auth/change_password.html')
