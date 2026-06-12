from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Float
from sqlalchemy.dialects.postgresql import JSONB
from app.core.db import db

class CveCache(db.Model):
    __tablename__ = 'cve_cache'

    id = Column(String, primary_key=True) # e.g. CVE-2021-44228
    description = Column(String, nullable=True)
    cvss_score = Column(Float, nullable=True)
    severity = Column(String, nullable=True) # e.g. HIGH, CRITICAL
    published_date = Column(DateTime(timezone=True), nullable=True)
    raw_data = Column(JSONB, nullable=True)
    cached_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    @property
    def badge_color(self):
        if not self.severity:
            return "secondary"
        sev = self.severity.upper()
        if "CRITICAL" in sev:
            return "danger"
        elif "HIGH" in sev:
            return "warning"
        elif "MEDIUM" in sev:
            return "info"
        elif "LOW" in sev:
            return "success"
        return "secondary"
