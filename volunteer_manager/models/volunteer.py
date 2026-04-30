from datetime import datetime
from ..database import db


class Skill(db.Model):
    __tablename__ = "skills"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    category = db.Column(db.String(100))

    def to_dict(self):
        return {"id": self.id, "name": self.name, "category": self.category}


class VolunteerSkill(db.Model):
    __tablename__ = "volunteer_skills"

    volunteer_id = db.Column(db.Integer, db.ForeignKey("volunteers.id"), primary_key=True)
    skill_id = db.Column(db.Integer, db.ForeignKey("skills.id"), primary_key=True)
    level = db.Column(db.String(20), default="competent")  # beginner, competent, expert

    skill = db.relationship("Skill")


class EmergencyContact(db.Model):
    __tablename__ = "emergency_contacts"

    id = db.Column(db.Integer, primary_key=True)
    volunteer_id = db.Column(db.Integer, db.ForeignKey("volunteers.id"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    relationship = db.Column(db.String(100))
    phone = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(200))

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "relationship": self.relationship,
            "phone": self.phone,
            "email": self.email,
        }


class AvailabilitySlot(db.Model):
    """Recurring availability window for a volunteer."""
    __tablename__ = "availability_slots"

    id = db.Column(db.Integer, primary_key=True)
    volunteer_id = db.Column(db.Integer, db.ForeignKey("volunteers.id"), nullable=False)
    day_of_week = db.Column(db.Integer)          # 0=Mon … 6=Sun; None = ad-hoc
    start_time = db.Column(db.Time)
    end_time = db.Column(db.Time)
    slot_type = db.Column(db.String(20), default="recurring")  # recurring | ad_hoc | unavailable
    date = db.Column(db.Date)                    # only for ad_hoc / unavailable

    def to_dict(self):
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        return {
            "id": self.id,
            "day_of_week": self.day_of_week,
            "day_name": days[self.day_of_week] if self.day_of_week is not None else None,
            "start_time": self.start_time.strftime("%H:%M") if self.start_time else None,
            "end_time": self.end_time.strftime("%H:%M") if self.end_time else None,
            "slot_type": self.slot_type,
            "date": self.date.isoformat() if self.date else None,
        }


class Volunteer(db.Model):
    __tablename__ = "volunteers"

    id = db.Column(db.Integer, primary_key=True)
    organisation_id = db.Column(db.Integer, db.ForeignKey("organisations.id"), nullable=False)

    # Personal details
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(50))
    date_of_birth = db.Column(db.Date)
    address = db.Column(db.Text)

    # Status
    status = db.Column(db.String(20), default="active")  # active | on_hold | left
    joined_date = db.Column(db.Date, default=datetime.utcnow)
    left_date = db.Column(db.Date)

    # Internal notes (coordinator only)
    notes = db.Column(db.Text)

    # Preferences
    preferred_contact = db.Column(db.String(20), default="email")  # email | sms | phone
    interests = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    organisation = db.relationship("Organisation", back_populates="volunteers")
    emergency_contacts = db.relationship("EmergencyContact", backref="volunteer", cascade="all, delete-orphan")
    skills = db.relationship("VolunteerSkill", backref="volunteer", cascade="all, delete-orphan")
    availability = db.relationship("AvailabilitySlot", backref="volunteer", cascade="all, delete-orphan")
    event_assignments = db.relationship("EventAssignment", back_populates="volunteer")
    dbs_checks = db.relationship("DBSCheck", back_populates="volunteer", cascade="all, delete-orphan")
    training_records = db.relationship("VolunteerTraining", back_populates="volunteer", cascade="all, delete-orphan")
    hours_logs = db.relationship("VolunteerHours", back_populates="volunteer", cascade="all, delete-orphan")
    consent_records = db.relationship("ConsentRecord", back_populates="volunteer", cascade="all, delete-orphan")

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def total_hours(self):
        return sum(h.hours for h in self.hours_logs)

    def to_dict(self, include_sensitive=False):
        data = {
            "id": self.id,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "full_name": self.full_name,
            "email": self.email,
            "phone": self.phone,
            "status": self.status,
            "joined_date": self.joined_date.isoformat() if self.joined_date else None,
            "interests": self.interests,
            "skills": [vs.skill.to_dict() for vs in self.skills],
            "total_hours": self.total_hours,
        }
        if include_sensitive:
            data.update({
                "date_of_birth": self.date_of_birth.isoformat() if self.date_of_birth else None,
                "address": self.address,
                "notes": self.notes,
                "preferred_contact": self.preferred_contact,
                "emergency_contacts": [ec.to_dict() for ec in self.emergency_contacts],
            })
        return data
