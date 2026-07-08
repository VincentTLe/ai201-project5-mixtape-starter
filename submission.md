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

Read all five issues before choosing. After the Milestone-2 reproduction pass:

- **Issue #1 — streak resets on Sunday** (`streak_service.py`) ✅ reproduced
- **Issue #4 — no notification on rating** (`notification_service.py`) ✅ reproduced
- **Issue #5 — last playlist song hidden** (`playlist_service.py`) ✅ reproduced
- **Issue #2 — feed shows yesterday** (`feed_service.py`) ✅ reproduced (4th / stretch)
- **Issue #3 — duplicate search results** (`search_service.py`) ⚠️ **does not reproduce** in this
  environment (see reproduction log) — kept as an optional latent-fix candidate.

---

## Milestone 2 — Reproduction Log

Reproduced each bug **before** touching code, using a throwaway diagnostic harness that calls the
service functions directly with controlled inputs (faster and more deterministic than firing HTTP
requests, per the brief). No repo files were changed; the one write (a test rating / a constructed
event) was rolled back.

### Issue #1 — streak resets on Sunday
Called `update_listening_streak(user, now)` in isolation with a fabricated user:
- `last_listened_at` = Sat 2026-07-11, `streak` = 12, `now` = **Sun** 2026-07-12 →
  result streak = **1** (expected 13). Bug reproduces.
- Control: `last_listened_at` = Sun, `now` = Mon → streak = 13 (correct on non-Sundays).
- Confirms kenji's report: the reset happens specifically when the update lands on a **Sunday**.

### Issue #2 — "Friends Listening Now" shows people from yesterday
Gave darius a single listening event **23 hours** ago (calendar day 2026-07-07) and no newer event,
then called `get_friends_listening_now(nova.id)` at wall-clock 2026-07-08. darius **still appears**,
because `RECENT_THRESHOLD` is a rolling `timedelta(hours=24)` window rather than "since midnight
today". Matches nova's report (a friend whose last listen was 11pm the night before still showing at
9am).

### Issue #4 — rating a shared song creates no notification
Counted `Notification` rows for the song's sharer (simone) before/after calling
`rate_song(kenji, "Crown Heights Anthem", 5)`: **before = 0, after = 0**, while the rating row was
saved (score = 5). No notification of any type is created for the sharer. Matches aaliya's report.

### Issue #5 — the last song in a playlist never shows up
Playlist "Friday Energy" has **7** rows in `playlist_entries`, but `get_playlist_songs()` returns
**6**. The missing title is exactly the one at the highest `position` (7 → `Harlem Renaissance`).
Matches darius's report that the most recently added song is always the hidden one.

### Issue #3 — duplicate search results (could NOT reproduce)
`search_songs("Anthem")` returns **1** result for "Crown Heights Anthem", even though the underlying
`outerjoin(song_tags)` produces **3** raw rows (the song has 3 tags). A broad `search_songs("a")`
matched 13 songs with **zero** duplicated titles. Root cause of the non-repro: SQLAlchemy's legacy
`Session.query(Song)` de-duplicates single-entity results by primary key before returning them, so
the fan-out from the tag join is collapsed. The code is *latently* wrong (a join without
`DISTINCT`), but it does not produce user-visible duplicates in this SQLAlchemy version. Documented
honestly rather than forcing a fix for a bug I can't trigger.

---

## Root Cause Analysis Entries

### Issue #1 — My listening streak keeps resetting

**How I reproduced it.** Called `update_listening_streak(user, now)` directly with a fabricated
user: `last_listened_at` = Saturday 2026-07-11, `listening_streak` = 12, `now` = Sunday
2026-07-12. Result: streak dropped to **1** instead of 13. Repeating with `now` = a Monday gave the
correct 13, which isolated the trigger to Sundays — exactly matching kenji's "both times it was a
Sunday".

**How I found the root cause.** Started at the route `GET /users/<id>/streak`
(`routes/users.py`) → `streak_service.get_streak()`, which just reads a stored column, so the value
must be set earlier. The write path is `POST /songs/<id>/listen` → `record_listening_event()` →
`update_listening_streak()`. Reading that function, the consecutive-day branch was
`elif days_since_last == 1 and today.weekday() != 6:`. The `today.weekday() != 6` clause stood out
because the docstring's rules say nothing about the day of the week. I confirmed with a one-liner
that `datetime.weekday()` returns **6 for Sunday**, so that clause is false only on Sundays.

**The root cause.** Python's `datetime.weekday()` uses Monday=0 … Sunday=6. The increment branch
required `days_since_last == 1 AND today.weekday() != 6`, so on any day that is a Sunday the
"listened yesterday" case failed its guard and execution fell through to the `else`, which resets
the streak to 1. There was no legitimate reason for the day-of-week condition — it silently threw
away the streak whenever the daily listen happened on a Sunday.

**My fix and side-effect check.** Removed the `and today.weekday() != 6` clause so the branch is
simply `elif days_since_last == 1:`. Verified all branches on both sides of the boundary: Sat→Sun
now gives 13, Sun→Mon gives 13, Fri→Sat gives 6, same-day (Sun→Sun) stays unchanged, a 2-day skip
still resets to 1, and a first-ever listen still starts at 1. No other code reads `weekday()`, and
`get_streak` is untouched, so nothing else is affected.

_Fix commit: `fix: increment streak on Sundays instead of resetting it`_

### Issue #4 — Notified when a friend adds my song to a playlist, but not when they rate it

**How I reproduced it.** Counted `Notification` rows for a song's sharer (simone) before and after
calling `rate_song(kenji, "Crown Heights Anthem", 5)`. The rating row was saved (score = 5) but the
sharer's notification count stayed at **0 → 0**, and no notification of any type appeared. The
working case (`add_to_playlist`) did create one, matching aaliya's "playlist add notifies, rating
doesn't".

**How I found the root cause.** Followed `POST /songs/<id>/rate` (`routes/songs.py`) →
`notification_service.rate_song()`. Both `rate_song` and `add_to_playlist` live in the same file,
so I compared them line by line, as the brief hinted. `add_to_playlist` ends with a guarded
`create_notification(...)` call targeting `song.shared_by`. `rate_song` saves the rating, commits,
and immediately `return rating` — there is no `create_notification` call anywhere in it. That was
the moment it was clearly the cause: the notification step doesn't exist, rather than existing but
misfiring.

**The root cause.** This is an architectural omission, not a typo. Notifications in Mixtape are only
created when a service function explicitly calls `create_notification`. `add_to_playlist` does this;
`rate_song` never did. So ratings persisted correctly (visible on the song) while the sharer was
never told, because the code path that would have created the notification was simply absent.

**My fix and side-effect check.** Added the same guarded notification block used by
`add_to_playlist`, placed right after the rating is committed in `rate_song`: if
`song.shared_by != user_id`, create a `"song_rated"` notification with body
`"{rater.username} rated your song '{song.title}' {score} stars."`. Verified: a friend rating now
produces exactly one `song_rated` notification with the correct body; a sharer rating their **own**
song produces none (the guard mirrors the playlist one); re-rating updates the score without adding
a duplicate `Rating` row (the model's `UniqueConstraint` still holds) — and `add_to_playlist`'s own
notification path is untouched and still fires. (Note: I separately observed a pre-existing,
unrelated crash when `add_to_playlist` appends a brand-new song — the `playlist_entries.position`
column is never set — but that is outside the five listed issues and I left it alone.)

_Fix commit: `fix: notify the sharer when their song is rated`_

### Issue #5 — The last song in a playlist never shows up

**How I reproduced it.** Compared the row count in `playlist_entries` for "Friday Energy" against
what `get_playlist_songs()` returned: **7 stored, 6 returned**. The missing title was always the one
at the highest `position` (7 → `Harlem Renaissance`). This matches darius's report that the hidden
song is always the most recently added, and that adding another song "frees" the previous one.

**How I found the root cause.** Followed `GET /playlists/<id>/songs` (`routes/playlists.py`) →
`playlist_service.get_playlist_songs()`. The query correctly selects all entries and orders them by
`playlist_entries.position` ascending. But the return line was
`return [song.to_dict() for song in songs[:-1]]`. The `[:-1]` slice was the smoking gun — it drops
the final element of an already-position-sorted list, and the function's own docstring says it
"returns all songs in the playlist", directly contradicting the slice.

**The root cause.** `songs[:-1]` returns every element except the last. Because `songs` is sorted by
ascending playlist position, "the last" is always the song with the highest position — i.e. the most
recently added. So the newest song was silently sliced off every time. Adding another song pushes a
new highest position, which is why the previously-hidden song reappears and the brand-new one takes
its place as the dropped element.

**My fix and side-effect check.** Changed the return to iterate the full list:
`return [song.to_dict() for song in songs]`. Verified all three seeded playlists now return their
full stored count (7/7 each) with position order preserved, a single-song playlist returns 1 (it
previously returned 0), and an empty playlist still returns 0 with no error. No other code calls
`get_playlist_songs`, and the ordering/query logic was left unchanged.

_Fix commit: `fix: return every playlist song instead of dropping the last`_

### Issue #2 — "Friends Listening Now" shows people from yesterday

**How I reproduced it.** Gave darius a single listening event 23 hours ago (calendar day
2026-07-07) and no newer one, then called `get_friends_listening_now(nova.id)` at wall-clock
2026-07-08 05:58 UTC. darius still appeared, because his 23h-old play was inside the rolling window.
This matches nova's report of a friend whose last listen was 11pm the night before still showing at
9am.

**How I found the root cause.** Followed `GET /feed/<id>/listening-now` (`routes/feed.py`) →
`feed_service.get_friends_listening_now()`. The query filters `ListeningEvent.listened_at >= cutoff`,
and `cutoff = datetime.now(timezone.utc) - RECENT_THRESHOLD` where `RECENT_THRESHOLD =
timedelta(hours=24)`. That defines "recent" as "within the last 24 hours from this instant" — a
rolling window — rather than "today". An event from 11pm last night is only ~10 hours old at 9am, so
it passes the filter; it only falls out 24 hours after it happened, i.e. at 11pm tonight — exactly
the "hangs around until the same time next day" behavior nova described.

**The root cause.** The feed used a rolling 24-hour cutoff instead of a calendar-day cutoff. The
requirement (and the feed's name, "listening *now* / today") is to show only friends who listened
**today**, but `now - 24h` reaches back into the previous calendar day for most of the morning and
afternoon, so yesterday-evening plays leak into today's feed.

**My fix and side-effect check.** Replaced the rolling cutoff with the start of the current calendar
day (UTC): `cutoff = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)`,
and removed the now-meaningless `RECENT_THRESHOLD` constant (and its unused `timedelta` import).
Verified on both sides of the midnight boundary: a friend who listened 23h ago (yesterday) is now
excluded, while friends who listened today are still shown. Confirmed `get_activity_feed` — which is
intentionally *not* date-filtered — is unaffected and still returns events, and that no other code
referenced `RECENT_THRESHOLD`. (Uses UTC calendar days, consistent with how the rest of the app
stores and compares timestamps.)

_Fix commit: `fix: scope listening-now feed to today, not a rolling 24h window`_
