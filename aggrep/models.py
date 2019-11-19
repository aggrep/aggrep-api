"""Database models."""
from enum import Enum

from flask import current_app
from sqlalchemy.ext.hybrid import hybrid_property
from werkzeug.security import check_password_hash, generate_password_hash

from aggrep import db
from aggrep.utils import decode_token, encode_token, now


class PKMixin:
    """Mixin that adds a primary key to each model."""

    __table_args__ = {"extend_existing": True}

    id = db.Column(db.Integer, primary_key=True)


class CRUDMixin:
    """Mixin that adds convenience methods for CRUD (create, read, update, delete) operations."""

    @classmethod
    def create(cls, **kwargs):
        """Create a new record and save it the database."""
        instance = cls(**kwargs)
        return instance.save()

    def update(self, commit=True, **kwargs):
        """Update specific fields of a record."""
        for attr, value in kwargs.items():
            setattr(self, attr, value)
        return commit and self.save() or self

    def save(self, commit=True):
        """Save the record."""
        db.session.add(self)
        if commit:
            db.session.commit()
        return self

    def delete(self, commit=True):
        """Remove the record from the database."""
        db.session.delete(self)
        return commit and db.session.commit()


class BaseModel(PKMixin, CRUDMixin, db.Model):
    """Base model class that includes CRUD convenience methods."""

    __abstract__ = True


class PaginatedAPIMixin:
    """Pagination mixin."""

    @staticmethod
    def to_collection_dict(query, page, per_page, endpoint, **kwargs):
        """Paginate a collection."""
        resources = query.paginate(page, per_page, False)
        data = {
            "items": [item.to_dict() for item in resources.items],
            "page": page,
            "per_page": per_page,
            "total_pages": resources.pages,
            "total_items": resources.total,
        }
        return data


class Category(BaseModel):
    """Category."""

    __tablename__ = "categories"
    slug = db.Column(db.String(32), unique=True, nullable=False)
    title = db.Column(db.String(140), unique=True, nullable=False)

    def to_dict(self):
        """Return as a dict."""
        return dict(id=self.id, slug=self.slug, title=self.title)

    def __repr__(self):
        """String representation."""
        return self.title


class Source(BaseModel):
    """Source model."""

    __tablename__ = "sources"
    slug = db.Column(db.String(32), unique=True, nullable=False)
    title = db.Column(db.String(140), nullable=False)

    def to_dict(self):
        """Return as a dict."""
        return dict(id=self.id, slug=self.slug, title=self.title)

    def __repr__(self):
        """String representation."""
        return self.title


class Status(BaseModel):
    """Feed status model."""

    __tablename__ = "feed_statuses"
    feed_id = db.Column(db.Integer, db.ForeignKey("feeds.id"), unique=True)
    update_datetime = db.Column(db.DateTime, nullable=False, default=now)
    update_frequency = db.Column(db.Integer, default=0)

    def __repr__(self):
        """String representation."""
        return "<{} last updated at {} (interval {})>".format(
            self.feed_id, self.update_datetime, self.update_frequency
        )


class Feed(BaseModel):
    """Feed model."""

    __tablename__ = "feeds"
    source_id = db.Column(db.Integer, db.ForeignKey("sources.id"))
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"))
    url = db.Column(db.String(255), nullable=False)

    # ORM Relationship
    source = db.relationship("Source", uselist=False, backref="feeds")
    category = db.relationship("Category", uselist=False, backref="feeds")
    status = db.relationship("Status", uselist=False, backref="feed")

    def to_dict(self):
        """Return as a dict."""
        return dict(
            source=self.source.to_dict(), category=self.category.to_dict(), url=self.url
        )

    def __repr__(self):
        """String representation."""
        return "<{}, {}>".format(self.source.title, self.category.title)


class Post(BaseModel, PaginatedAPIMixin):
    """Post model."""

    __tablename__ = "posts"
    feed_id = db.Column(db.Integer, db.ForeignKey("feeds.id"))
    title = db.Column(db.String(255), nullable=False)
    desc = db.Column(db.Text())
    link = db.Column(db.String(255), nullable=False)
    published_datetime = db.Column(db.DateTime, nullable=False, default=now, index=True)
    ingested_datetime = db.Column(db.DateTime, nullable=False, default=now)

    feed = db.relationship("Feed", uselist=False, backref="posts")

    entities = db.relationship("Entity", backref="post")
    enqueued_entities = db.relationship("EntityProcessQueue", backref="post")

    similar_posts = db.relationship(
        "Similarity", backref="post", foreign_keys="Similarity.source_id",
    )

    enqueued_similartities = db.relationship(
        "SimilarityProcessQueue", backref="post",
    )

    @hybrid_property
    def click_count(self):
        """Number of clicks (instance level)."""
        return len(self.clicks)

    @click_count.expression
    def click_count(self):
        """Number of clicks (class level)."""
        return db.select([db.func.count(Click.id)]).where(Click.post_id == self.id)

    @hybrid_property
    def similar_count(self):
        """Number of similar posts (instance level)."""
        return len(self.similar_posts)

    @similar_count.expression
    def similar_count(self):
        """Number of similar posts (class level)."""
        return db.select([db.func.count(Similarity.id)]).where(
            Similarity.source_id == self.id
        )

    @hybrid_property
    def bookmark_count(self):
        """Number of bookmarks (instance level)."""
        return len(self.bookmarks)

    @bookmark_count.expression
    def bookmark_count(self):
        """Number of bookmarks (class level)."""
        return db.select([db.func.count(Bookmark.id)]).where(
            Bookmark.post_id == self.id
        )

    def to_dict(self):
        """Return as a dict."""
        payload = dict(
            id=self.id,
            title=self.title,
            link=self.link,
            similar_count=self.similar_count,
            feed=self.feed.to_dict(),
            published_datetime=self.published_datetime,
        )
        return payload

    def __repr__(self):
        """String representation."""
        return "{}: {}".format(self.id, self.title)


class EntityProcessQueue(BaseModel):
    """Entity queue model."""

    __tablename__ = "entity_queue"
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id", ondelete="CASCADE"), unique=True)


class Entity(BaseModel):
    """Entity model."""

    __tablename__ = "entities"
    entity = db.Column(db.String(40), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id", ondelete="CASCADE"), index=True)


class SimilarityProcessQueue(BaseModel):
    """Similarity queue model."""

    __tablename__ = "similarity_queue"
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id", ondelete="CASCADE"), unique=True)


class Similarity(BaseModel):
    """Similarity model."""

    __tablename__ = "similarities"
    source_id = db.Column(db.Integer, db.ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    related_id = db.Column(db.Integer, db.ForeignKey("posts.id", ondelete="CASCADE"))


class Jobs(Enum):
    """Enum of background jobs."""

    COLLECT = "collect"
    PROCESS = "process"
    RELATE = "relate"


class JobLock(BaseModel):
    """Job lock model."""

    __tablename__ = "joblock"
    job = db.Column(db.Enum(Jobs))
    lock_datetime = db.Column(db.DateTime, nullable=False, default=now)

    def __repr__(self):
        """String representation."""
        return "<Job '{}' locked at {}>".format(self.job, self.lock_datetime)


class Click(BaseModel):
    """Click model."""

    __tablename__ = "clicks"
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    action_datetime = db.Column(db.DateTime, nullable=False, default=now)

    user = db.relationship("User", uselist=False, backref="clicks")
    post = db.relationship("Post", uselist=False, backref="clicks")


class Bookmark(BaseModel):
    """Bookmark model."""

    __tablename__ = "bookmarks"
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    action_datetime = db.Column(db.DateTime, nullable=False, default=now)

    user = db.relationship("User", uselist=False, backref="bookmarks")
    post = db.relationship("Post", uselist=False, backref="bookmarks")


db.Index("ix_user_bookmark", Bookmark.user_id, Bookmark.post_id)


user_excluded_sources = db.Table(
    "user_excluded_sources",
    db.Column("user_id", db.Integer(), db.ForeignKey("user.id")),
    db.Column("source_id", db.Integer(), db.ForeignKey("sources.id")),
)


user_excluded_categories = db.Table(
    "user_excluded_categories",
    db.Column("user_id", db.Integer(), db.ForeignKey("user.id")),
    db.Column("category_id", db.Integer(), db.ForeignKey("categories.id")),
)


class User(BaseModel):
    """User model."""

    email = db.Column(db.String(255), unique=True)
    password = db.Column(db.String(255), nullable=True)
    active = db.Column(db.Boolean(), default=True)
    confirmed = db.Column(db.Boolean(), default=False)
    last_seen = db.Column(db.DateTime)

    # ORM relationships
    excluded_sources = db.relationship(
        "Source",
        secondary=user_excluded_sources,
        lazy="subquery",
        backref=db.backref("user_excluded_sources", lazy=True),
    )
    excluded_categories = db.relationship(
        "Category",
        secondary=user_excluded_categories,
        lazy="subquery",
        backref=db.backref("user_excluded_categories", lazy=True),
    )

    def set_password(self, password):
        """Set a user's password."""
        self.password = generate_password_hash(password)
        self.save()

    def check_password(self, password):
        """Check a user's password."""
        return check_password_hash(self.password, password)

    @staticmethod
    def get_user_from_identity(identity):
        """Get a user from a JWT."""
        try:
            return User.query.filter_by(email=identity).first()
        except Exception:
            return None

    def get_reset_password_token(self):
        """Get a password reset token."""
        expires_in = 60 * 15  # 15 minutes
        secret = current_app.config["SECRET_KEY"]
        return encode_token("reset_password", self.id, secret, expires_in=expires_in)

    @staticmethod
    def verify_reset_password_token(token):
        """Verify a password reset token."""
        secret = current_app.config["SECRET_KEY"]
        id = decode_token("reset_password", secret, token)
        if id is None:
            return None

        return User.query.get(id)

    def get_email_confirm_token(self):
        """Get an email confirmation token."""
        expires_in = 60 * 60 * 24  # 24 hours
        secret = current_app.config["SECRET_KEY"]
        return encode_token("email_confirm", self.id, secret, expires_in=expires_in)

    @staticmethod
    def verify_email_confirm_token(token):
        """Verify an email confirmation token."""
        secret = current_app.config["SECRET_KEY"]
        id = decode_token("email_confirm", secret, token)
        if id is None:
            return None

        return User.query.get(id)

    def update_excluded_categories(self, categories):
        """Update a user's excluded categories."""
        self.excluded_categories = categories
        self.save()

    def update_excluded_sources(self, sources):
        """Update a user's excluded sources."""
        self.excluded_sources = sources
        self.save()

    def to_dict(self):
        """Return as a dict."""
        return dict(email=self.email, confirmed=self.confirmed)

    def __repr__(self):
        """String representation."""
        return self.email