"""Emergency fallback UI for the one SciGuard API/event workflow.

This surface contains no detection, policy, write-back, or recovery logic. It
either streams the same FastAPI run as the primary command center or renders the
same integrity-bound recorded replay.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
REPLAY_ID = "inc-wp6-flagship"
REPLAY_ROOT = ROOT / "examples" / "replays" / REPLAY_ID
DEFAULT_API = "http://127.0.0.1:8000"


def _request_json(url: str, *, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=30) as response:  # noqa: S310 - operator-supplied local API
        return json.loads(response.read())


def _stream_events(url: str) -> list[dict]:
    request = Request(url, headers={"Accept": "text/event-stream"})
    events = []
    with urlopen(request, timeout=60) as response:  # noqa: S310 - operator-supplied local API
        for raw in response:
            line = raw.decode().strip()
            if not line.startswith("data: "):
                continue
            frame = json.loads(line[6:])
            if "event" in frame:
                events.append(frame["event"])
    return events


def _load_replay() -> tuple[dict, list[dict]]:
    manifest = json.loads((REPLAY_ROOT / "manifest.json").read_text(encoding="utf-8"))
    events = [
        json.loads(line)
        for line in (REPLAY_ROOT / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    return manifest, events


def _render(manifest: dict, events: list[dict], mode: str) -> None:
    state = manifest.get("incident_state", "UNKNOWN")
    st.title("SciGuard Autopilot · Fallback")
    st.caption("Thin client for the same immutable Event workflow used by Command Center.")
    left, middle, right = st.columns(3)
    left.metric("Incident", manifest.get("incident_id", "—"))
    middle.metric("State", state)
    right.metric("Mode", mode)

    signal = next((event for event in events if event["event_type"] == "SIGNAL_DETECTED"), None)
    escalation = next(
        (event for event in events if event["event_type"] == "ESCALATION_DECIDED"),
        None,
    )
    if signal:
        payload = signal["payload"]
        st.subheader("Sentinel signal")
        st.write(signal["summary"])
        st.json(
            {
                "severity": payload.get("severity"),
                "matched_rules": payload.get("matched_rule_ids"),
                "initial_review_scope": len(payload.get("initial_scope", [])) + 1,
                "decision_assets_reached": payload.get("decision_assets_reached"),
                "escalation": escalation["payload"] if escalation else None,
            }
        )

    st.subheader("Immutable event timeline")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "#": event["sequence"],
                    "actor": event["actor"],
                    "type": event["event_type"],
                    "summary": event["summary"],
                }
                for event in events
            ]
        ),
        hide_index=True,
        width="stretch",
    )

    policies = [event for event in events if event["event_type"] == "POLICY_DECIDED"]
    if policies:
        st.subheader("Deterministic control plan")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "asset": event["payload"].get("name"),
                        "affected": event["payload"].get("affected"),
                        "decision": event["payload"].get("decision"),
                        "status": event["payload"].get("catalog_status"),
                    }
                    for event in policies
                ]
            ),
            hide_index=True,
            width="stretch",
        )


st.set_page_config(page_title="SciGuard Fallback", page_icon="🧪", layout="wide")
mode = st.sidebar.radio("Source", ["Recorded replay", "Live API"])

if mode == "Recorded replay":
    replay_manifest, replay_events = _load_replay()
    _render(replay_manifest, replay_events, "RECORDED_REPLAY")
else:
    api_base = st.sidebar.text_input("SciGuard API", DEFAULT_API).rstrip("/")
    try:
        health = _request_json(f"{api_base}/healthz")
        st.sidebar.success(f"API {health['status']}")
    except (OSError, URLError, ValueError) as exc:
        st.sidebar.error(f"API unavailable: {exc}")
        st.stop()

    if st.sidebar.button("Start live incident", type="primary"):
        view = _request_json(f"{api_base}/api/runs", method="POST", body={})
        st.session_state["run_view"] = view
    if "run_view" not in st.session_state:
        st.info("Start a live incident or switch to the verified recorded replay.")
        st.stop()

    run_view = st.session_state["run_view"]
    live_events = _stream_events(f"{api_base}{run_view['events_url']}")
    live_view = _request_json(f"{api_base}{run_view['state_url']}")
    _render(live_view["manifest"], live_events, "LIVE")
