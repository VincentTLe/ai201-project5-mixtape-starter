"""
tests/test_notifications.py — Mixtape

Regression tests for Issue #4: rating a shared song must notify the sharer,
mirroring the notification that add_to_playlist already sends.

Before the fix, rate_song saved the rating but never created a notification,
so `test_rating_a_song_notifies_the_sharer` failed (0 notifications created).
"""

import pytest
from app import create_app, db
from models import User, Song, Notification
from services.notification_service import rate_song


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def seed(app):
    """A sharer who shared a song, and a separate friend who can rate it."""
    with app.app_context():
        sharer = User(username="sharer", email="sharer@example.com")
        friend = User(username="friend", email="friend@example.com")
        db.session.add_all([sharer, friend])
        db.session.flush()

        song = Song(title="Crown Heights Anthem", artist="Borough Kings",
                    genre="rap", shared_by=sharer.id)
        db.session.add(song)
        db.session.commit()
        yield {"sharer": sharer, "friend": friend, "song": song}


def test_rating_a_song_notifies_the_sharer(app, seed):
    """A friend rating a shared song creates a 'song_rated' notification for the sharer."""
    with app.app_context():
        sharer_id = seed["sharer"].id
        friend_id = seed["friend"].id
        song_id = seed["song"].id

        before = Notification.query.filter_by(
            user_id=sharer_id, notification_type="song_rated"
        ).count()

        rate_song(friend_id, song_id, 5)

        notifs = Notification.query.filter_by(
            user_id=sharer_id, notification_type="song_rated"
        ).all()
        assert len(notifs) == before + 1  # Bug: rate_song created no notification
        assert "rated your song" in notifs[-1].body


def test_rating_your_own_song_does_not_notify(app, seed):
    """A user rating their own shared song should not notify themselves."""
    with app.app_context():
        sharer_id = seed["sharer"].id
        song_id = seed["song"].id

        rate_song(sharer_id, song_id, 4)

        count = Notification.query.filter_by(
            user_id=sharer_id, notification_type="song_rated"
        ).count()
        assert count == 0
