"""Run opt-in real LLM evals with fixture tools, or an offline Fake comparison."""

import argparse
import json
import math
import os

from merval_agent.adapters.llm.context import PROMPT_VERSIONS
from merval_agent.config import Settings
from merval_agent.evaluation import evaluate, load_cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--fake", action="store_true")
    parser.add_argument(
        "--case-id",
        action="append",
        choices=[case["id"] for case in load_cases()],
        help="Evaluate only these cases (repeat flag for multiple); default is the full dataset",
    )
    parser.add_argument(
        "--prompt-version",
        choices=tuple(PROMPT_VERSIONS),
        help="Select actual prompt text; overrides AGENT_PROMPT_VERSION for this evaluation",
    )
    parser.add_argument(
        "--llm-min-interval-seconds",
        type=float,
        default=0,
        help="Minimum interval between all LLM requests, including retries (RPM); ignored for Fake",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=0,
        help="Minimum wait between real case/repetition runs; ignored for Fake",
    )
    parser.add_argument(
        "--provider-error-cooldown-seconds",
        type=float,
        default=0,
        help="Minimum wait after a run ends with provider rate limit; ignored for Fake",
    )
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    if any(
        not math.isfinite(x) or x < 0
        for x in (
            args.delay_seconds,
            args.provider_error_cooldown_seconds,
            args.llm_min_interval_seconds,
        )
    ):
        parser.error("Delays must be finite and nonnegative")
    if not args.fake and os.getenv("RUN_LLM_TESTS") != "1":
        parser.error("Set RUN_LLM_TESTS=1 to authorize external LLM requests")
    settings = Settings()
    if args.prompt_version:
        settings = settings.model_copy(update={"agent_prompt_version": args.prompt_version})
    if not args.fake and settings.llm_provider not in ("compatible", "gemini"):
        parser.error("Set LLM_PROVIDER=compatible or gemini")
    if not args.fake and not (
        settings.llm_base_url and settings.llm_model and settings.llm_api_key.get_secret_value()
    ):
        parser.error("Configure LLM_BASE_URL, LLM_MODEL and LLM_API_KEY")
    report, path = evaluate(
        settings,
        runs=args.runs,
        fake=args.fake,
        delay_seconds=args.delay_seconds,
        provider_error_cooldown_seconds=args.provider_error_cooldown_seconds,
        llm_min_interval_seconds=args.llm_min_interval_seconds,
        **(
            {"cases": [case for case in load_cases() if case["id"] in args.case_id]}
            if args.case_id
            else {}
        ),
    )
    print(json.dumps(report["metrics"], indent=2))
    print(f"Report: {path}")
    baseline = path.parent / "fake_baseline.json"
    if not args.fake and baseline.exists():
        fake = json.loads(baseline.read_text(encoding="utf-8"))
        if fake.get("evaluator_version") != report["evaluator_version"]:
            print("Fake baseline uses older metric definitions; regenerate it before comparing.")
            return exit_code(report)
        if sorted((row["id"], row["run"]) for row in fake["cases"]) != sorted(
            (row["id"], row["run"]) for row in report["cases"]
        ):
            print("Fake baseline covers different cases/repetitions; metrics are not comparable.")
            return exit_code(report)
        print("Metric                           Fake          Real")
        for key, value in report["metrics"].items():
            print(f"{key:32} {str(fake['metrics'].get(key)):13} {value}")
    return exit_code(report)


def exit_code(report):
    if report["metrics"]["failed_cases"]:
        return 1
    if (
        not report["cases"]
        or report["metrics"]["provider_error_cases"]
        or report["metrics"]["not_evaluated_cases"]
    ):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
