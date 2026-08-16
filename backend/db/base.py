from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for every SQLAlchemy mirror model.

    See models.py for why these exist and the rule that governs them.
    """
