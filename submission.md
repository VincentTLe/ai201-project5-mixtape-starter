# Project 5 — Mixtape Bug Hunt · Submission

> Author: Vincent Le
> Branch: `bugfix/mixtape`

---

## AI Usage

_(Written in Milestone 4 — see bottom of document once bug work is complete.)_

---

## Codebase Map

_Written before opening any issue, as proof of orientation._

### High-level architecture

Mixtape is a Flask JSON API (no HTML front-end). It uses the **application-factory** pattern
(`create_app()` in `app.py`) and **SQLAlchemy** for persistence against a SQLite file
(`instance/mixtape.db`). Every HTTP endpoint follows the same two-layer split:

```
HTTP request → routes/<area>.py  (parse input, call one service, format JSON response)
                     │
                     ▼
              services/<area>.py (ALL business logic + DB access lives here)
                     │
                     ▼
              models.py          (SQLAlchemy models + to_dict serializers)
```

The routes never touch the database directly for business logic — they parse the request,
call exactly one service function, and wrap the return value in `jsonify`. This is a
consistent, deliberate pattern across all four blueprints. **The README explicitly says the
bugs all live in the `services/` layer**, which matches this separation: a broken endpoint is
almost always a broken service function.

### Files and their roles

| File | Responsibility |
|------|----------------|
| `app.py` | App factory. Creates the Flask app, configures the SQLite URI, initializes `db`, registers the four blueprints under URL prefixes (`/songs`, `/playlists`, `/users`, `/feed`), and calls `db.create_all()`. `db = SQLAlchemy()` is defined here and imported everywhere else. |
| `models.py` | All SQLAlchemy models + three association tables. Each model has a `to_dict()` used for JSON serialization. |
| `seed_data.py` | Populates the DB with 5 users, songs, tags, friendships, listening events, ratings, and playlists for local testing. |
| `routes/songs.py` | `/songs/search`, `/songs/<id>`, `/songs/<id>/rate` (POST), `/songs/<id>/listen` (POST). |
| `routes/playlists.py` | Create playlist, get playlist metadata, get playlist songs, add song to playlist (POST). |
| `routes/users.py` | Get user, `/users/<id>/streak`, `/users/<id>/notifications`, mark notification read (POST). |
| `routes/feed.py` | `/feed/<id>/listening-now`, `/feed/<id>/activity`. |
| `services/streak_service.py` | Records a listening event and updates the user's consecutive-day streak. |
| `services/feed_service.py` | "Friends Listening Now" (recent) + general activity feed. |
| `services/search_service.py` | Song search by title/artist, single-song lookup. |
| `services/notification_service.py` | Creates/retrieves notifications; also owns `add_to_playlist` and `rate_song`. |
| `services/playlist_service.py` | Create/read playlists and their ordered songs. |

### Data model (`models.py`)

Eight tables — five entity models and three association tables:

- **`User`** — has `listening_streak` and `last_listened_at` columns (streak state lives on the
  user, not in a separate table). `friends` is a self-referential many-to-many via `friendships`.
- **`Song`** — `shared_by` FK links a song back to the user who shared it. This matters for
  notifications: interactions notify `song.shared_by`.
- **`ListeningEvent`** — one row per play, with `listened_at`. Drives both the streak and the feed.
- **`Rating`** — one row per (user, song) with a `UniqueConstraint`, so a user re-rating a song
  updates the existing row rather than creating a duplicate. Score is 1–5.
- **`Playlist`** — collaborative by default. Its songs come through the `playlist_entries`
  association table.
- **`Notification`** — `user_id` is the *recipient*; has `notification_type`, `body`, `read`.
- Association tables: `friendships` (symmetric user↔user), `song_tags` (song↔tag,
  **many-to-many** — one song can have several tags), and **`playlist_entries`** — the important
  one: it is not a plain join table, it carries an explicit **`position`** integer plus
  `added_by` and `added_at`. So playlist order is stored explicitly, not derived from insertion
  order.

### Data flow trace #1 — a user adds a shared song to a playlist (→ notification)

1. `POST /playlists/<playlist_id>/songs` with JSON `{song_id, added_by}` hits `add_song()` in
   `routes/playlists.py`.
2. The route validates both fields are present, then calls
   `notification_service.add_to_playlist(playlist_id, song_id, added_by)`.
3. `add_to_playlist` loads the song, the adder, and the playlist; appends the song to
   `playlist.songs` (which writes a `playlist_entries` row) and commits.
4. **If the adder is not the original sharer** (`song.shared_by != added_by_user_id`), it calls
   `create_notification(user_id=song.shared_by, type="song_added_to_playlist", body=...)`, which
   inserts a `Notification` row for the sharer and commits.
5. The sharer later sees it via `GET /users/<id>/notifications` →
   `notification_service.get_notifications()`.

### Data flow trace #2 — a user listens to a song (→ streak update)

1. `POST /songs/<song_id>/listen` with `{user_id}` → `listen()` in `routes/songs.py`.
2. Route calls `streak_service.record_listening_event(user_id, song_id)`.
3. That function inserts a `ListeningEvent(listened_at=now)`, then calls
   `update_listening_streak(user, now)`.
4. `update_listening_streak` compares `today` to the date of `user.last_listened_at`:
   - never listened → streak = 1
   - listened today already → no change
   - listened exactly yesterday → streak += 1
   - otherwise → streak reset to 1
   Then it stamps `user.last_listened_at = now` and commits.
5. `GET /users/<id>/streak` → `streak_service.get_streak()` returns `user.listening_streak`.

### Patterns I noticed

1. **Route = thin, service = thick.** Every route parses input, calls one service, formats JSON.
   All logic and DB access is in `services/`. Debugging starts from the route and immediately
   drops into the matching service.
2. **`to_dict()` everywhere.** Serialization lives on the models, so services return lists of
   dicts and routes just `jsonify` them.
3. **Notifications are sharer-centric.** They target `song.shared_by` and are only created for
   *interactions by other people*. `notification_service` is the single place notifications are
   born — anything that should notify has to call `create_notification` itself.
4. **Ordering is explicit for playlists** (`playlist_entries.position`) but implicit-by-timestamp
   for feeds/streaks (`listened_at`). Boundary bugs are likely to cluster around these
   date/position comparisons.
5. **UTC everywhere** via `datetime.now(timezone.utc)`, but stored SQLite datetimes come back
   naive — the streak service already has to re-attach `tzinfo` before comparing.

---

## Bug Selection

Read all five issues before choosing. Planned picks (≥3 required):

- **Issue #1 — streak resets on Sunday** (`streak_service.py`)
- **Issue #4 — no notification on rating** (`notification_service.py`)
- **Issue #5 — last playlist song hidden** (`playlist_service.py`)
- Stretch: **Issue #2 — feed shows yesterday** (`feed_service.py`) and
  **Issue #3 — duplicate search results** (`search_service.py`).

---

## Root Cause Analysis Entries

_(Filled in one at a time during Milestone 3, each committed separately.)_
