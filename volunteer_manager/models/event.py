from datetime import datetime
from ..database import db


class EventRole(db.Model):
    """A role slot within a specific event (how many of each role needed)."""
    __tablename__ = "event_roles"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    slots_required = db.Column(db.Integer, default=1)

    role = db.relationship("Role", back_populates="event_roles")
    assignments = db.relationship("EventAssignment", back_populates="event_role")

    @property
    def slots_filled(self):
        return sum(1 for a in self.assignments if a.status == "confirmed")

    @property
    def slots_available(self):
        if self.slots_required is None:
            return None
        return max(0, self.slots_required - self.slots_filled)

    def to_dict(self):
        return {
            "id": self.id,
            "role": self.role.to_dict() if self.role else None,
            "slots_required": self.slots_required,
            "slots_filled": self.slots_filled,
            "slots_available": self.slots_available,
        }


class EventAssignment(db.Model):
    """A volunteer assigned to a specific role slot in an event."""
    __tablename__ = "event_assignments"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    event_role_id = db.Column(db.Integer, db.ForeignKey("event_roles.id"), nullable=False)
    volunteer_id = db.Column(db.Integer, db.ForeignKey("volunteers.id"), nullable=False)
    status = db.Column(db.String(20), default="assigned")  # assigned | confirmed | declined | no_show
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)

    volunteer = db.relationship("Volunteer", back_populates="event_assignments")
    event_role = db.relationship("EventRole", back_populates="assignments")
    event = db.relationship("Event", back_populates="assignments")

    def to_dict(self):
        return {
            "id": self.id,
            "volunteer": self.volunteer.to_dict() if self.volunteer else None,
            "role": self.event_role.role.to_dict() if self.event_role and self.event_role.role else None,
            "status": self.status,
            "assigned_at": self.assigned_at.isoformat() if self.assigned_at else None,
            "notes": self.notes,
        }


class AttendanceRecord(db.Model):
    __tablename__ = "attendance_records"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    volunteer_id = db.Column(db.Integer, db.ForeignKey("volunteers.id"), nullable=False)
    checked_in_at = db.Column(db.DateTime)
    checked_out_at = db.Column(db.DateTime)
    present = db.Column(db.Boolean)
    recorded_by = db.Column(db.String(200))

    volunteer = db.relationship("Volunteer")
    event = db.relationship("Event", back_populates="attendance_records")

    def to_dict(self):
        return {
            "id": self.id,
            "volunteer_id": self.volunteer_id,
            "volunteer_name": self.volunteer.full_name if self.volunteer else None,
            "present": self.present,
            "checked_in_at": self.checked_in_at.isoformat() if self.checked_in_at else None,
            "checked_out_at": self.checked_out_at.isoformat() if self.checked_out_at else None,
        }


class VolunteerHours(db.Model):
    __tablename__ = "volunteer_hours"

    id = db.Column(db.Integer, primary_key=True)
    volunteer_id = db.Column(db.Integer, db.ForeignKey("volunteers.id"), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"))
    date = db.Column(db.Date, nullable=False)
    hours = db.Column(db.Float, nullable=False)
    miles_travelled = db.Column(db.Float, default=0.0)
    description = db.Column(db.String(300))
    logged_by = db.Column(db.String(200))

    volunteer = db.relationship("Volunteer", back_populates="hours_logs")
    event = db.relationship("Event")

    def to_dict(self):
        return {
            "id": self.id,
            "date": self.date.isoformat() if self.date else None,
            "hours": self.hours,
            "miles_travelled": self.miles_travelled,
            "description": self.description,
            "event_id": self.event_id,
        }


class Event(db.Model):
    __tablename__ = "events"

    id = db.Column(db.Integer, primary_key=True)
    organisation_id = db.Column(db.Integer, db.ForeignKey("organisations.id"), nullable=False)
    name = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text)
    location = db.Column(db.String(300))
    start_datetime = db.Column(db.DateTime, nullable=False)
    end_datetime = db.Column(db.DateTime)
    event_type = db.Column(db.String(50), default="one_off")  # one_off | recurring | rota
    status = db.Column(db.String(20), default="planned")      # planned | active | completed | cancelled
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    organisation = db.relationship("Organisation", back_populates="events")
    event_roles = db.relationship("EventRole", backref="event", cascade="all, delete-orphan")
    assignments = db.relationship("EventAssignment", back_populates="event", cascade="all, delete-orphan")
    attendance_records = db.relationship("AttendanceRecord", back_populates="event", cascade="all, delete-orphan")

    @property
    def total_volunteers_needed(self):
        return sum(er.slots_required or 0 for er in self.event_roles)

    @property
    def total_volunteers_assigned(self):
        return sum(er.slots_filled for er in self.event_roles)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "location": self.location,
            "start_datetime": self.start_datetime.isoformat() if self.start_datetime else None,
            "end_datetime": self.end_datetime.isoformat() if self.end_datetime else None,
            "event_type": self.event_type,
            "status": self.status,
            "total_volunteers_needed": self.total_volunteers_needed,
            "total_volunteers_assigned": self.total_volunteers_assigned,
            "roles": [er.to_dict() for er in self.event_roles],
        }
