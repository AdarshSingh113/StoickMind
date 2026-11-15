"""LLM-as-judge: did the conversation meet the agent's success criteria?

Every agent in the Studio has a goal and success criteria written in plain English
("customer receives a routine within budget and shows interest in buying").
A second LLM call reads the transcript (including tool calls) and judges it.

Why an LLM judge? Success like "showed buying intent" can't be checked with a regex.
Why be careful? Judges are themselves models: they can be lenient, swayed by long
answers, or confused. So we:
- give a strict rubric and ask for a short reason (auditable),
- include the tool calls, so it can check grounding (were prices really from tools?),
- force a small JSON output and parse it defensively,
- store every verdict, so judge quality can itself be reviewed later (Phase 8).
"""

from __future__ import annotations

import json
import re
from datetime import datetime

from kotler import db
from kotler.agent.studio import AgentConfig
from kotler.llm import LLMError

JUDGE_PROMPT = """You are a strict quality reviewer for an AI {role} named {name} at an Indian skincare store.

Agent's goal: {goal}
Success criteria: {success_criteria}

Read the conversation below (TOOL lines show what the agent looked up and what came back).
Judge ONLY what is in the transcript. Check:
- Were the success criteria met?
- Did the agent stay grounded (products and prices only from TOOL results)?
- Did it follow its instructions and respect any budget?

Reply with ONLY this JSON, nothing else:
{{"achieved": true or false, "score": 1-5, "reason": "one or two sentences"}}

Score guide: 5 = excellent, criteria fully met; 3 = partly met or minor issues; 1 = failed or harmful.
If the conversation simply hasn't reached the goal yet (e.g. still mid-quiz), achieved is false and say so.

CONVERSATION
{transcript}"""


def format_transcript(rows: list[dict], max_tool_chars: int = 700) -> str:
    lines = []
    for r in rows:
        if r["role"] == "user":
            lines.append(f"CUSTOMER: {r['content']}")
        elif r["role"] == "assistant":
            lines.append(f"AGENT: {r['content']}")
        else:
            result = (r["content"] or "")[:max_tool_chars]
            lines.append(f"TOOL {r.get('tool_name')}({r.get('tool_args') or ''}) -> {result}")
    return "\n".join(lines)


def parse_verdict(text: str | None) -> dict:
    """Pull the JSON verdict out of the model's reply, tolerating code fences or extra words."""
    if text:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                data = json.loads(match.group(0))
                score = int(data.get("score", 0))
                return {"achieved": bool(data.get("achieved")), "score": min(max(score, 1), 5),
                        "reason": str(data.get("reason", "")).strip()[:500]}
            except (json.JSONDecodeError, ValueError, TypeError):
                pass
    return {"achieved": False, "score": 1, "reason": "The judge's answer couldn't be read.", "invalid": True}


def judge_conversation(llm, agent: AgentConfig, conversation_id: int, save: bool = True) -> dict:
    rows = db.query_df("SELECT role, content, tool_name, tool_args FROM messages WHERE conversation_id = ? "
                       "ORDER BY id", (conversation_id,)).to_dict("records")
    if not any(r["role"] == "user" for r in rows):
        return {"achieved": False, "score": 1, "reason": "No conversation to judge yet."}
    prompt = JUDGE_PROMPT.format(role=agent.role, name=agent.name, goal=agent.goal,
                                 success_criteria=agent.success_criteria, transcript=format_transcript(rows))
    try:
        resp = llm.chat([{"role": "user", "content": prompt}], tools=None, temperature=0)
    except LLMError as e:
        return {"achieved": False, "score": 1, "reason": e.user_message, "error": str(e)[:300]}
    verdict = parse_verdict(resp.content)
    if save and not verdict.get("invalid"):
        with db.get_conn() as conn:
            conn.execute("INSERT INTO conversation_scores (conversation_id, agent_slug, agent_version, achieved, "
                         "score, reason, created_at) VALUES (?,?,?,?,?,?,?)",
                         (conversation_id, agent.slug, agent.version, int(verdict["achieved"]), verdict["score"],
                          verdict["reason"], datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    return verdict


def agent_scorecard(slug: str) -> dict:
    """Success rate and average score for one agent, per version (did v3 beat v2?)."""
    df = db.query_df("SELECT agent_version AS version, COUNT(*) AS judged, ROUND(100.0 * AVG(achieved), 0) AS "
                     "success_pct, ROUND(AVG(score), 1) AS avg_score FROM conversation_scores WHERE agent_slug = ? "
                     "GROUP BY agent_version ORDER BY agent_version DESC", (slug,))
    return {"by_version": df}
