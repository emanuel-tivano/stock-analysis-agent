"""Inspect a local Phase 1 execution without displaying its private user request."""

import argparse
import json
import sqlite3

from merval_agent.config import Settings
from merval_agent.memory.sqlite import read_trace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace_id")
    parser.add_argument("--database", default=None)
    args = parser.parse_args()
    try:
        trace = read_trace(args.database or Settings().database_path, args.trace_id)
    except (sqlite3.Error, OSError):
        parser.exit(1, "Cannot read local trace database.\n")
    if trace is None:
        parser.exit(1, "Trace not found.\n")
    print(f"trace_id={trace['trace_id']} status={trace['final_status']}")
    if not trace["events"]:
        print("Legacy execution: only tool trace available.")
    for event in trace["events"] or trace["tool_trace"]:
        if event.get("event", "").startswith("ACTION_"):
            print(
                f"HITL {event['event']} action={event['action_id']} version={event['version']} "
                f"{event['transition']} actor={event['actor']} at={event['timestamp']}"
            )
        if event.get("event") in ("LLM_SUCCEEDED", "LLM_FAILED", "DECISION_VALIDATION_FAILED"):
            print(
                "LLM provider={provider} model={model} version={version} attempt={attempt} "
                "http={http} class={classification} validation={validation} latency_ms={latency}".format(
                    provider=event.get("provider"),
                    model=event.get("model"),
                    version=event.get("modelVersion"),
                    attempt=event.get("retry_number", 0) + 1,
                    http=event.get("http_status"),
                    classification=event.get("error_class"),
                    validation=event.get("validation_outcome"),
                    latency=event.get("latency_ms"),
                )
            )
        if event.get("generation"):
            print("GENERATION " + json.dumps(event["generation"], ensure_ascii=True))
        if event.get("market_data"):
            print("MARKET " + json.dumps(event["market_data"], ensure_ascii=True))
        print(json.dumps(event, ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    main()
