from datetime import datetime, date
from ..database import db


class DBSCheck(db.Model):
    __tablename__ = "dbs_checks"

    id = db.Column(db.Integer, primary_key=True)
    volunteer_id = db.Column(db.Integer, db.ForeignKey("volunteers.id"), nullable=False)
    check_type = db.Column(db.String(20), nullable=False)  # basic | standard | enhanced
    reference_number = db.Column(db.String(100))
    issue_date = db.Column(db.Date, nullable=False)
    expiry_date = db.Column(db.Date)
    evidence_filename = db.Column(db.String(300))  # stored securely, filename only
    verified_by = db.Column(db.String(200))
    verified_at = db.Column(db.DateTime)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    volunteer = db.relationship("Volunteer", back_populates="dbs_checks")

    @property
    def is_expired(self):
        if self.expiry_date:
            return self.expiry_date < date.today()
        return False

    @property
    def days_until_expiry(self):
        if self.expiry_date:
            return (self.expiry_date - date.today()).days
        return None

    def to_dict(self):
        return {
            "id": self.id,
            "check_type": self.check_type,
            "reference_number": self.reference_number,
            "issue_date": self.issue_date.isoformat() if self.issue_date else None,
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "is_expired": self.is_expired,
            "days_until_expiry": self.days_until_expiry,
            "verified_by": self.verified_by,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
        }


class TrainingRequirement(db.Model):
    """Organisation-level training requirement (e.g. 'Safeguarding Level 1')."""
    __tablename__ = "training_requirements"

    id = db.Column(db.Integer, primary_key=True)
    organisation_id = db.Column(db.Integer, db.ForeignKey("organisations.id"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    validity_months = db.Column(db.Integer)   # how long before renewal required; None = no expiry
    mandatory = db.Column(db.Boolean, default=True)
    applies_to_role_id = db.Column(db.Integer, db.ForeignKey("roles.id"))  # None = all roles

    volunteer_records = db.relationship("VolunteerTraining", back_populates="requirement")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "validity_months": self.validity_months,
            "mandatory": self.mandatory,
            "applies_to_role_id": self.applies_to_role_id,
        }


class VolunteerTraining(db.Model):
    __tablename__ = "volunteer_training"

    id = db.Column(db.Integer, primary_key=True)
    volunteer_id = db.Column(db.Integer, db.ForeignKey("volunteers.id"), nullable=False)
    requirement_id = db.Column(db.Integer, db.ForeignKey("training_requirements.id"), nullable=False)
    completed_date = db.Column(db.Date, nullable=False)
    expiry_date = db.Column(db.Date)
    evidence_filename = db.Column(db.String(300))
    notes = db.Column(db.Text)

    volunteer = db.relationship("Volunteer", back_populates="training_records")
    requirement = db.relationship("TrainingRequirement", back_populates="volunteer_records")

    @property
    def is_expired(self):
        if self.expiry_date:
            return self.expiry_date < date.today()
        return False

    @property
    def days_until_expiry(self):
        if self.expiry_date:
            return (self.expiry_date - date.today()).days
        return None

    def to_dict(self):
        return {
            "id": self.id,
            "requirement": self.requirement.to_dict() if self.requirement else None,
            "completed_date": self.completed_date.isoformat() if self.completed_date else None,
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "is_expired": self.is_expired,
            "days_until_expiry": self.days_until_expiry,
        }


class SafeguardingConcern(db.Model):
    """Secure logging of safeguarding concerns. Restricted visibility."""
    __tablename__ = "safeguarding_concerns"

    id = db.Column(db.Integer, primary_key=True)
    organisation_id = db.Column(db.Integer, db.ForeignKey("organisations.id"), nullable=False)
    volunteer_id = db.Column(db.Integer, db.ForeignKey("volunteers.id"))
    reported_by = db.Column(db.String(200), nullable=False)
    reported_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    description = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(100))       # e.g. welfare, conduct, disclosure
    severity = db.Column(db.String(20), default="low")  # low | medium | high | critical
    status = db.Column(db.String(20), default="open")   # open | under_review | closed | escalated
    escalated_to = db.Column(db.String(200))
    resolution_notes = db.Column(db.Text)
    resolved_at = db.Column(db.DateTime)

    # Audit trail – appended JSON log of who accessed this record
    access_log = db.Column(db.Text, default="[]")

    volunteer = db.relationship("Volunteer")

    def to_dict(self):
        return {
            "id": self.id,
            "volunteer_id": self.volunteer_id,
            "reported_by": self.reported_by,
            "reported_at": self.reported_at.isoformat() if self.reported_at else None,
            "category": self.category,
            "severity": self.severity,
            "status": self.status,
            "escalated_to": self.escalated_to,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }


class ConsentRecord(db.Model):
    __tablename__ = "consent_records"

    id = db.Column(db.Integer, primary_key=True)
    volunteer_id = db.Column(db.Integer, db.ForeignKey("volunteers.id"), nullable=False)
    consent_type = db.Column(db.String(100), nullable=False)  # privacy_notice | photo | email_marketing
    version = db.Column(db.String(20))
    granted = db.Column(db.Boolean, nullable=False)
    granted_at = db.Column(db.DateTime)
    withdrawn_at = db.Column(db.DateTime)
    ip_address = db.Column(db.String(50))

    volunteer = db.relationship("Volunteer", back_populates="consent_records")

    def to_dict(self):
        return {
            "id": self.id,
            "consent_type": self.consent_type,
            "version": self.version,
            "granted": self.granted,
            "granted_at": self.granted_at.isoformat() if self.granted_at else None,
            "withdrawn_at": self.withdrawn_at.isoformat() if self.withdrawn_at else None,
        }
