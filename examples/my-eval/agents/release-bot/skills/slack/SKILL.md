---
name: slack
description: Compose, search, and post to Slack channels, DMs, and canvases.
plugin: slack
---

# Slack

The Slack MCP plugin exposes the same 13 tools shipped by the official Slack
Claude Code plugin. The full schemas land in your tool list at session start;
this skill summarises *how to sequence them well*.

## Workflows

### Posting a message to a known channel name

If you only know the channel by name (e.g. `#releases`, not its `C…` ID):

1. `slack_search_channels(query: "releases")` → returns the channel's
   `id` (looks like `C09RELEASE01`).
2. `slack_send_message(channel_id: "C09…", message: "...")` → posts and
   returns `message_link`. Quote the link in your final answer.

### Posting a DM

`channel_id` may be a user_id for DMs. Resolve the user via
`slack_search_users(query: "name or email")`, then pass their `id` as
`channel_id` to `slack_send_message`.

### Drafts instead of sends

If the user hasn't approved exact wording, prefer
`slack_send_message_draft(channel_id, message)` over `slack_send_message`.
A draft can be reviewed in Slack's UI before it's sent.

### Searching

- `slack_search_public` — public channels only; safe to call without user
  confirmation.
- `slack_search_public_and_private` — includes DMs and private channels;
  ask first if uncertain.
- Use search modifiers in the `query` string: `in:#channel`, `from:@user`,
  `before:YYYY-MM-DD`, `after:YYYY-MM-DD`, `is:thread`, quotes for exact
  phrases.

### Reading a thread

You need both the parent `channel_id` AND the parent `message_ts`. If you
only have a search hit, pull the `ts` from the result and pass it as
`message_ts` to `slack_read_thread`.

## Gotchas

- **Markdown, not Slack mrkdwn.** `slack_send_message` accepts standard
  markdown (`**bold**`, `_italic_`, `` `code` ``). Don't use Slack's older
  `*bold*`/`_italic_` mrkdwn syntax.
- **No Connect channels.** Posting to externally-shared (Slack Connect)
  channels is not supported by these tools.
- **Canvas Markdown is its own dialect.** When using `slack_create_canvas` /
  `slack_update_canvas`, the content uses *Canvas-flavored Markdown* (user
  refs as `![](@U…)`, channel refs as `![](#C…)`, ATX headings only). The
  full spec is embedded in the tool's description — read it before writing
  canvas content.
- **Current user is `U09J02RP7MK`.** Use this when the task says "me" or
  asks to DM the runner themselves.
