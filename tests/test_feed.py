"""
tests/test_feed.py — Mixtape

Regression tests for Issue #2: "Friends Listening Now" must show only friends
who listened *today* (current calendar day), not anyone within a rolling 24h window.

Before the fix, the cutoff was `now - timedelta(hours=24)`, so a play from just
before midnight last night still appeared this morning —
`test_listening_now_excludes_yesterday_evening` failed.
"""

import pytest
from datetime import datetime, timedelta, timezone
from app import create_app, db
from models import User, Song, ListeningEvent, friendships
from services.feed_service import get_friends_listening_now


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def seed(app):
    """
    'me' is friends with two people:
      - fresh: listened today (just now)
      - stale: listened at 23:59:59 *yesterday* (previous calendar day)
    """
    with app.app_context():
        me = User(username="me", email="me@example.com")
        fresh = User(username="fresh", email="fresh@example.com")
        stale = User(username="stale", email="stale@example.com")
        db.session.add_all([me, fresh, stale])
        db.session.flush()

        for other in (fresh, stale):
            db.session.execute(friendships.insert().values(user_id=me.id, friend_id=other.id))
            db.session.execute(friendships.insert().values(user_id=other.id, friend_id=me.id))

        song = Song(title="Track", artist="Various", shared_by=me.id)
        db.session.add(song)
        db.session.flush()

        now = datetime.now(timezone.utc)
        start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_late = start_of_today - timedelta(seconds=1)  # 23:59:59 yesterday

        db.session.add(ListeningEvent(user_id=fresh.id, song_id=song.id, listened_at=now))
        db.session.add(ListeningEvent(user_id=stale.id, song_id=song.id, listened_at=yesterday_late))
        db.session.commit()
        yield {"me": me, "fresh": fresh, "stale": stale}


def test_listening_now_includes_today(app, seed):
    """A friend who listened today appears in the feed."""
    with app.app_context():
        usernames = [f["friend"]["username"] for f in get_friends_listening_now(seed["me"].id)]
        assert "fresh" in usernames


def test_listening_now_excludes_yesterday_evening(app, seed):
    """A friend whose last listen was late yesterday must NOT appear today."""
    with app.app_context():
        usernames = [f["friend"]["username"] for f in get_friends_listening_now(seed["me"].id)]
        # Bug: the rolling 24h window kept 'stale' in the feed all of today.
        assert "stale" not in usernames
