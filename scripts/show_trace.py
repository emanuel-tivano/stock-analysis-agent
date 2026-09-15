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
        print(json.dumps(event, ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    main()
