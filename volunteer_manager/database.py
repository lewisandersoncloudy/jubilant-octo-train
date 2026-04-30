from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def init_db(app):
    db.init_app(app)
    with app.app_context():
        db.create_all()
        _seed_demo_data()


def _seed_demo_data():
    """Seed one demo organisation so the app is usable out of the box."""
    from .models.organisation import Organisation
    if Organisation.query.first():
        return

    from .models.volunteer import Skill
    from .models.compliance import TrainingRequirement
    from datetime import date

    org = Organisation(
        name="Greenfield Community Council",
        type="council",
        contact_email="admin@greenfield.gov.example",
    )
    db.session.add(org)
    db.session.flush()

    skills = [
        Skill(name="First Aid", category="Health & Safety"),
        Skill(name="Safeguarding", category="Compliance"),
        Skill(name="Event Management", category="Operations"),
        Skill(name="Driving", category="Logistics"),
        Skill(name="IT / Digital", category="Technical"),
        Skill(name="Youth Work", category="Community"),
        Skill(name="Gardening", category="Grounds"),
    ]
    db.session.add_all(skills)
    db.session.flush()

    training_reqs = [
        TrainingRequirement(
            organisation_id=org.id,
            name="Safeguarding Level 1",
            description="Introduction to safeguarding principles.",
            validity_months=24,
            mandatory=True,
        ),
        TrainingRequirement(
            organisation_id=org.id,
            name="GDPR Awareness",
            description="Data protection basics for volunteers.",
            validity_months=12,
            mandatory=True,
        ),
        TrainingRequirement(
            organisation_id=org.id,
            name="Health & Safety Induction",
            validity_months=36,
            mandatory=True,
        ),
    ]
    db.session.add_all(training_reqs)

    # Default message templates
    from .models.communication import MessageTemplate as MT
    templates = [
        MT(
            organisation_id=org.id,
            name="Welcome New Volunteer",
            template_type="joining",
            subject="Welcome to {{organisation_name}}, {{volunteer_name}}!",
            body=(
                "Dear {{volunteer_name}},\n\n"
                "We're delighted to welcome you as a volunteer with {{organisation_name}}.\n\n"
                "Please log in to your volunteer portal to complete your profile and let us know your availability.\n\n"
                "Thank you for giving your time.\n\nThe Volunteer Team"
            ),
        ),
        MT(
            organisation_id=org.id,
            name="Event Reminder",
            template_type="reminder",
            subject="Reminder: {{event_name}} on {{event_date}}",
            body=(
                "Dear {{volunteer_name}},\n\n"
                "This is a friendly reminder that you are scheduled to volunteer at:\n\n"
                "  Event: {{event_name}}\n"
                "  Date:  {{event_date}}\n"
                "  Location: {{event_location}}\n\n"
                "Please reply if your availability has changed.\n\nThank you!"
            ),
        ),
        MT(
            organisation_id=org.id,
            name="Thank You",
            template_type="thanks",
            subject="Thank you, {{volunteer_name}}!",
            body=(
                "Dear {{volunteer_name}},\n\n"
                "Thank you so much for volunteering at {{event_name}}. "
                "Your contribution makes a real difference to our community.\n\n"
                "With gratitude,\n{{organisation_name}}"
            ),
        ),
        MT(
            organisation_id=org.id,
            name="DBS Expiry Reminder",
            template_type="dbs_expiry",
            subject="Action required: your DBS check expires soon",
            body=(
                "Dear {{volunteer_name}},\n\n"
                "Your DBS check is due to expire on {{expiry_date}}. "
                "Please contact us to arrange a renewal before this date.\n\n"
                "{{organisation_name}}"
            ),
        ),
    ]
    db.session.add_all(templates)
    db.session.commit()
