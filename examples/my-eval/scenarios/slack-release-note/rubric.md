# Rubric: slack-release-note

The agent must post a release note to the `#releases` channel (channel_id
`C09RELEASE01`, discovered via `slack_search_channels`). Determinism is enforced
by the `mock_state` assertion; this rubric judges *message quality*.

## Anchors

1. **Channel** — message targets `#releases` (channel_id `C09RELEASE01`).
2. **Brevity** — body is at most 4 sentences. Award the anchor if at most 4.
3. **Backend mention** — references the FastAPI backend (or version 1.2.0, or both).
4. **Feature coverage** — touches at least two of: SQLModel users + items,
   JWT login, Alembic migrations, FastAPI. Buzzword spam without context does
   NOT count.
5. **Tone** — short, professional, no marketing fluff, no emoji bombs.

## Scoring (return a score in 0..1)

- 1.0: all anchors; reads like a real release note in a small team.
- 0.8: all anchors with a minor issue (e.g. 5 sentences instead of 4).
- 0.6: 3 anchors hit.
- 0.4: wrong channel or off-topic body; or only 2 anchors.
- 0.2 or below: did not actually post, or posted nonsense.

A good answer hits anchors 1, 3, and 4 at minimum.
