from __future__ import annotations

import os
from flask import Flask
from .database import db, init_db


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # Defaults
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-change-in-production")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "DATABASE_URL", "sqlite:///volunteer_manager.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB upload limit

    if config:
        app.config.update(config)

    db.init_app(app)

    with app.app_context():
        # Import models so SQLAlchemy sees them before create_all
        from .models import (  # noqa: F401
            Volunteer, EmergencyContact, Skill, VolunteerSkill, AvailabilitySlot,
            Role, RoleSkillRequirement,
            Event, EventRole, EventAssignment, AttendanceRecord, VolunteerHours,
            DBSCheck, TrainingRequirement, VolunteerTraining,
            SafeguardingConcern, ConsentRecord,
            MessageTemplate, Message,
            Organisation,
        )
        db.create_all()

        # Seed demo data on first run
        from .database import _seed_demo_data
        _seed_demo_data()

    # Register blueprints
    from .routes.volunteers import bp as volunteers_bp
    from .routes.roles import bp as roles_bp
    from .routes.events import bp as events_bp
    from .routes.compliance import bp as compliance_bp
    from .routes.scheduling import bp as scheduling_bp
    from .routes.communications import bp as communications_bp
    from .routes.reporting import bp as reporting_bp
    from .routes.ui import bp as ui_bp

    app.register_blueprint(volunteers_bp,    url_prefix="/api/volunteers")
    app.register_blueprint(roles_bp,         url_prefix="/api/roles")
    app.register_blueprint(events_bp,        url_prefix="/api/events")
    app.register_blueprint(compliance_bp,    url_prefix="/api/compliance")
    app.register_blueprint(scheduling_bp,    url_prefix="/api/scheduling")
    app.register_blueprint(communications_bp, url_prefix="/api/communications")
    app.register_blueprint(reporting_bp,     url_prefix="/api/reports")
    app.register_blueprint(ui_bp)

    return app
