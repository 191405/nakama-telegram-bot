"""SQLAlchemy ORM models for the file-sharing bot."""

from __future__ import annotations

import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all models."""


class User(Base):
    """Telegram user who has interacted with the bot."""

    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(String(512), default="")
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    persona: Mapped[str] = mapped_column(String(50), default="nakama")
    xp: Mapped[int] = mapped_column(Integer, default=0)
    joined_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_active: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    uploaded_files: Mapped[list[File]] = relationship(
        back_populates="uploader", lazy="selectin"
    )
    downloads: Mapped[list[Download]] = relationship(
        back_populates="user", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<User {self.user_id} @{self.username}>"


class Category(Base):
    """File category for organizing content."""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    emoji: Mapped[str] = mapped_column(String(10), default="📁")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    # Relationships
    files: Mapped[list[File]] = relationship(
        back_populates="category", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Category {self.emoji} {self.name}>"


class File(Base):
    """A file stored on Telegram's servers, tracked by file_id."""

    __tablename__ = "files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    file_unique_id: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(
        String(50), default="document"
    )  # document, video, audio, photo
    file_size: Mapped[int] = mapped_column(BigInteger, default=0)
    category_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    uploaded_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True
    )
    download_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    category: Mapped[Category | None] = relationship(
        back_populates="files", lazy="selectin"
    )
    uploader: Mapped[User | None] = relationship(
        back_populates="uploaded_files", lazy="selectin"
    )
    downloads: Mapped[list[Download]] = relationship(
        back_populates="file", lazy="selectin", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<File #{self.id} {self.file_name}>"

    @property
    def type_emoji(self) -> str:
        """Return an emoji for the file type."""
        return {
            "document": "📄",
            "video": "🎬",
            "audio": "🎵",
            "photo": "🖼️",
            "animation": "🎞️",
        }.get(self.file_type, "📁")

    @property
    def human_size(self) -> str:
        """Return human-readable file size."""
        if not self.file_size:
            return "Unknown"
        size = float(self.file_size)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


class Download(Base):
    """Tracks each file download for analytics."""

    __tablename__ = "downloads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.user_id"), nullable=False
    )
    file_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("files.id", ondelete="CASCADE"), nullable=False
    )
    downloaded_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    user: Mapped[User] = relationship(back_populates="downloads", lazy="selectin")
    file: Mapped[File] = relationship(back_populates="downloads", lazy="selectin")


class AnimeRequest(Base):
    """User requests for missing anime series or episodes."""

    __tablename__ = "anime_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.user_id"), nullable=False
    )
    anime_title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), default="pending"
    )  # pending, fulfilled, rejected
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    user: Mapped[User] = relationship(lazy="selectin")


class Watchlist(Base):
    """Personal watchlist bookmark for anime series."""

    __tablename__ = "watchlist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.user_id"), nullable=False
    )
    series_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), default="watching"
    )  # watching, plan_to_watch, completed
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(lazy="selectin")


class TriviaRecord(Base):
    """Records daily anime trivia questions and user scores."""

    __tablename__ = "trivia_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.user_id"), nullable=False
    )
    question_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    points_awarded: Mapped[int] = mapped_column(Integer, default=0)
    answered_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(lazy="selectin")

