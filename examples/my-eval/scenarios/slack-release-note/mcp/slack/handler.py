"""Slack mock behaviour, ported from the capa-benchmark Node handlers.

Each function takes (args, ctx) where ctx.state.data is the mutable state dict
and ctx.state.mutate(fn) applies an in-place mutation. Returning a plain dict
is auto-wrapped as MCP text content by the engine. The engine records every
call to state['__calls__'] for `tool_called` assertions.
"""
from __future__ import annotations

import time

CURRENT_USER_ID = "U09J02RP7MK"


# ── helpers ──────────────────────────────────────────────────────────────────


def _next_ts() -> str:
    ms = int(time.time() * 1000)
    return f"{ms // 1000}.{str(ms % 1000).rjust(6, '0')}"


def _next_canvas_id(state) -> str:
    n = len(state.get("canvases", [])) + 1
    return f"F09CANVAS{str(n).rjust(3, '0')}"


def _find_channel(state, channel_id):
    if not channel_id:
        return None
    for c in state["channels"]:
        if c["id"] == channel_id:
            return c
    name = channel_id.lstrip("#")
    for c in state["channels"]:
        if c["name"] == name:
            return c
    for u in state["users"]:
        if u["id"] == channel_id:
            return {"id": channel_id, "name": f"dm:{u['name']}", "is_im": True, "is_user": True}
    return None


def _find_user(state, user_id):
    if not user_id:
        return None
    return next((u for u in state["users"] if u["id"] == user_id), None)


def _match_query(q, *fields) -> bool:
    if not q:
        return True
    needle = str(q).lower()
    return any(needle in str(f or "").lower() for f in fields)


def _message_link(team, channel_id, ts) -> str:
    return f"https://{team['domain']}.slack.com/archives/{channel_id}/p{ts.replace('.', '')}"


# ── handlers ─────────────────────────────────────────────────────────────────


def slack_send_message(args, ctx):
    state = ctx.state.data
    ch = _find_channel(state, args.get("channel_id"))
    if not ch:
        return {"ok": False, "error": "channel_not_found"}
    if not args.get("message"):
        return {"ok": False, "error": "message_required"}
    ts = _next_ts()
    message = {
        "channel_id": ch["id"],
        "channel_name": ch["name"],
        "user": CURRENT_USER_ID,
        "text": args["message"],
        "ts": ts,
        "thread_ts": args.get("thread_ts"),
        "reply_broadcast": bool(args.get("reply_broadcast")),
    }
    ctx.state.mutate(lambda s: s["messages"].append(message))
    return {
        "ok": True,
        "channel": ch["id"],
        "ts": ts,
        "message_link": _message_link(state["team"], ch["id"], ts),
        "message": message,
    }


def slack_schedule_message(args, ctx):
    state = ctx.state.data
    ch = _find_channel(state, args.get("channel_id"))
    if not ch:
        return {"ok": False, "error": "channel_not_found"}
    scheduled_id = f"Q{int(time.time() * 1000)}"
    item = {
        "scheduled_message_id": scheduled_id,
        "channel_id": ch["id"],
        "post_at": args.get("post_at"),
        "text": args.get("message"),
        "thread_ts": args.get("thread_ts"),
    }
    ctx.state.mutate(lambda s: s["scheduled"].append(item))
    return {"ok": True, "scheduled_message_id": scheduled_id, "channel": ch["id"], "post_at": args.get("post_at")}


def slack_send_message_draft(args, ctx):
    state = ctx.state.data
    ch = _find_channel(state, args.get("channel_id"))
    if not ch:
        return {"ok": False, "error": "channel_not_found"}
    draft_id = f"D{int(time.time() * 1000)}"
    ctx.state.mutate(
        lambda s: s["drafts"].append(
            {
                "draft_id": draft_id,
                "channel_id": ch["id"],
                "message": args.get("message"),
                "thread_ts": args.get("thread_ts"),
            }
        )
    )
    return {"ok": True, "draft_id": draft_id, "channel_link": f"https://app.slack.com/client/{state['team']['id']}/{ch['id']}"}


def slack_create_canvas(args, ctx):
    state = ctx.state.data
    if not args.get("title") or not args.get("content"):
        return {"ok": False, "error": "invalid_content"}
    canvas_id = _next_canvas_id(state)
    ctx.state.mutate(
        lambda s: s["canvases"].append(
            {"canvas_id": canvas_id, "title": args["title"], "content": args["content"], "section_id_mapping": {}}
        )
    )
    canvas_url = f"https://{state['team']['domain']}.slack.com/docs/{state['team']['id']}/{canvas_id}"
    return {"ok": True, "canvas_id": canvas_id, "canvas_url": canvas_url, "title": args["title"]}


def slack_update_canvas(args, ctx):
    state = ctx.state.data
    found = {"c": None}

    def _do(s):
        c = next((x for x in s["canvases"] if x["canvas_id"] == args.get("canvas_id")), None)
        if not c:
            return
        action = args.get("action", "append")
        content = args.get("content", "")
        if action == "replace" and not args.get("section_id"):
            c["content"] = content
        elif action == "append":
            c["content"] = f"{c['content']}\n\n{content}"
        elif action == "prepend":
            c["content"] = f"{content}\n\n{c['content']}"
        elif action == "replace" and args.get("section_id"):
            c["content"] = f"{c['content']}\n\n<!-- section {args['section_id']} replaced -->\n{content}"
        found["c"] = c

    ctx.state.mutate(_do)
    c = found["c"]
    if not c:
        return {"ok": False, "error": "canvas_not_found"}
    return {
        "ok": True,
        "canvas_id": c["canvas_id"],
        "canvas_url": f"https://{state['team']['domain']}.slack.com/docs/{state['team']['id']}/{c['canvas_id']}",
        "section_id_mapping": c["section_id_mapping"],
    }


def slack_read_canvas(args, ctx):
    state = ctx.state.data
    c = next((x for x in state["canvases"] if x["canvas_id"] == args.get("canvas_id")), None)
    if not c:
        return {"ok": False, "error": "canvas_not_found"}
    return {"ok": True, "canvas_id": c["canvas_id"], "title": c["title"], "content": c["content"], "section_id_mapping": c["section_id_mapping"]}


def _search_messages(state, q, public_only, limit):
    out = []
    for m in state["messages"]:
        ch = next((c for c in state["channels"] if c["id"] == m["channel_id"]), None)
        if public_only and (not ch or ch.get("is_private")):
            continue
        if not _match_query(q, m.get("text"), m.get("channel_name")):
            continue
        out.append(
            {
                "type": "message",
                "text": m["text"],
                "ts": m["ts"],
                "user": m["user"],
                "channel": {"id": m["channel_id"], "name": m["channel_name"]},
                "permalink": _message_link(state["team"], m["channel_id"], m["ts"]),
            }
        )
    return out[:limit]


def slack_search_public(args, ctx):
    state = ctx.state.data
    q = args.get("query", "")
    matches = _search_messages(state, q, public_only=True, limit=args.get("limit", 20))
    out = {"ok": True, "query": q, "messages": {"total": len(matches), "matches": matches}}
    if "files" in (args.get("content_types") or "messages"):
        out["files"] = {"total": 0, "matches": []}
    return out


def slack_search_public_and_private(args, ctx):
    state = ctx.state.data
    q = args.get("query", "")
    matches = _search_messages(state, q, public_only=False, limit=args.get("limit", 20))
    return {"ok": True, "query": q, "messages": {"total": len(matches), "matches": matches}}


def slack_search_channels(args, ctx):
    state = ctx.state.data
    q = args.get("query", "")
    types = (args.get("channel_types") or "public_channel").split(",")
    want_public = "public_channel" in types
    want_private = "private_channel" in types
    out = []
    for c in state["channels"]:
        if c.get("is_archived") and not args.get("include_archived"):
            continue
        if c.get("is_private") and not want_private:
            continue
        if not c.get("is_private") and not want_public:
            continue
        if not _match_query(q, c["name"], (c.get("topic") or {}).get("value"), (c.get("purpose") or {}).get("value")):
            continue
        out.append(
            {
                "id": c["id"],
                "name": c["name"],
                "is_private": c.get("is_private"),
                "is_archived": c.get("is_archived"),
                "topic": c.get("topic"),
                "purpose": c.get("purpose"),
            }
        )
    return {"ok": True, "channels": out[: args.get("limit", 20)], "response_metadata": {"next_cursor": ""}}


def slack_search_users(args, ctx):
    state = ctx.state.data
    q = args.get("query", "")
    users = [
        u
        for u in state["users"]
        if _match_query(q, u.get("name"), u.get("real_name"), (u.get("profile") or {}).get("email"), (u.get("profile") or {}).get("title"), (u.get("profile") or {}).get("team"))
    ]
    return {"ok": True, "users": users[: args.get("limit", 20)]}


def slack_read_channel(args, ctx):
    state = ctx.state.data
    ch = _find_channel(state, args.get("channel_id"))
    if not ch:
        return {"ok": False, "error": "channel_not_found"}
    msgs = sorted(
        (m for m in state["messages"] if m["channel_id"] == ch["id"] and not m.get("thread_ts")),
        key=lambda m: float(m["ts"]),
        reverse=True,
    )[: args.get("limit", 100)]
    return {"ok": True, "channel": {"id": ch["id"], "name": ch["name"]}, "messages": msgs, "has_more": False, "response_metadata": {"next_cursor": ""}}


def slack_read_thread(args, ctx):
    state = ctx.state.data
    ch = _find_channel(state, args.get("channel_id"))
    if not ch:
        return {"ok": False, "error": "channel_not_found"}
    target = args.get("message_ts")
    msgs = sorted(
        (m for m in state["messages"] if m["channel_id"] == ch["id"] and (m["ts"] == target or m.get("thread_ts") == target)),
        key=lambda m: float(m["ts"]),
    )[: args.get("limit", 100)]
    return {"ok": True, "channel": {"id": ch["id"], "name": ch["name"]}, "messages": msgs, "has_more": False}


def slack_read_user_profile(args, ctx):
    state = ctx.state.data
    u = _find_user(state, args.get("user_id") or CURRENT_USER_ID)
    return {"ok": True, "user": u} if u else {"ok": False, "error": "user_not_found"}


HANDLERS = {
    "slack_send_message": slack_send_message,
    "slack_schedule_message": slack_schedule_message,
    "slack_send_message_draft": slack_send_message_draft,
    "slack_create_canvas": slack_create_canvas,
    "slack_update_canvas": slack_update_canvas,
    "slack_read_canvas": slack_read_canvas,
    "slack_search_public": slack_search_public,
    "slack_search_public_and_private": slack_search_public_and_private,
    "slack_search_channels": slack_search_channels,
    "slack_search_users": slack_search_users,
    "slack_read_channel": slack_read_channel,
    "slack_read_thread": slack_read_thread,
    "slack_read_user_profile": slack_read_user_profile,
}
