"""Thin CLI client for the one FastAPI/SciGuardRuntime incident workflow."""

from __future__ import annotations

import json
import os
from urllib.request import Request, urlopen


def main() -> None:
    api = os.environ.get("SCIGUARD_API_URL", "http://127.0.0.1:8000").rstrip("/")
    request = Request(
        f"{api}/api/runs",
        data=b"{}",
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=30) as response:  # noqa: S310 - configured local API
        view = json.loads(response.read())
    print(f"incident={view['manifest']['incident_id']} mode=LIVE")

    stream = Request(f"{api}{view['events_url']}", headers={"Accept": "text/event-stream"})
    with urlopen(stream, timeout=60) as response:  # noqa: S310 - configured local API
        for raw in response:
            line = raw.decode().strip()
            if not line.startswith("data: "):
                continue
            event = json.loads(line[6:])["event"]
            print(
                f"#{event['sequence']:02d} {event['actor']:<24} "
                f"{event['event_type']}: {event['summary']}"
            )


if __name__ == "__main__":
    main()
