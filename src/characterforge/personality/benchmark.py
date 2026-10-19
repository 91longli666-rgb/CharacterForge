"""P1 baseline: original scenarios, two prompt conditions, saved evidence."""

import argparse
import csv
from dataclasses import asdict
from datetime import datetime, timezone
import json
import platform
from pathlib import Path
import statistics
import sys

from characterforge.llm.ollama import OllamaClient, OllamaError
from .card import ROOT, Conversation, file_sha256, load_card, read_json, system_prompt

CONDITIONS = ("rules_only", "rules_plus_background")
SCORE_FIELDS = ("personality_consistency", "language_naturalness", "humor_drama",
                "non_repetition", "relevance")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def default_card() -> Path:
    private = ROOT / "private_assets/personality/cartman-inspired.json"
    return private if private.exists() else ROOT / "characters/original_demo/card.json"


def parser(description: str) -> argparse.ArgumentParser:
    arg = argparse.ArgumentParser(description=description)
    arg.add_argument("--character", type=Path, default=default_card())
    arg.add_argument("--settings", type=Path, default=ROOT / "experiments/personality/settings.json")
    arg.add_argument("--endpoint", help="Override; must remain http://127.0.0.1:<port>")
    arg.add_argument("--model", help="Override installed model tag")
    return arg


def load_settings(args) -> dict:
    settings = read_json(args.settings)
    if args.endpoint:
        settings["endpoint"] = args.endpoint
    if args.model:
        settings["model"] = args.model
    if settings.get("think") is not False:
        raise ValueError("P1 requires think=false.")
    return settings


def request_kwargs(settings: dict, stream: bool) -> dict:
    return {"stream": stream, "keep_alive": settings["keep_alive"],
            "runner": settings["runner"]}


def summary(records: list[dict]) -> dict:
    result = {}
    for condition in CONDITIONS:
        rows = [r for r in records if r["condition"] == condition and r["status"] == "ok"]
        elapsed = [r["result"]["elapsed_s"] for r in rows]
        ttft = [r["result"]["ttft_s"] for r in rows if r["result"]["ttft_s"] is not None]
        result[condition] = {"successful_requests": len(rows),
            "failed_requests": sum(r["condition"] == condition and r["status"] != "ok" for r in records),
            "elapsed_median_s": statistics.median(elapsed) if elapsed else None,
            "elapsed_max_s": max(elapsed) if elapsed else None,
            "visible_text_ttft_median_s": statistics.median(ttft) if ttft else None,
            "truncated_requests": sum(r["result"]["final"].get("done_reason") == "length" for r in rows),
            "thinking_observed_requests": sum(r["result"]["thinking_observed"] for r in rows)}
    return result


def write_outputs(out: Path, evidence: dict, scenarios: list[dict]):
    write_json(out / "results.json", evidence)
    columns = ["condition", "scenario_id", "scenario_name", "turn", "status", "elapsed_s", "ttft_s",
               "prompt_eval_count", "eval_count", "tokens_per_s", "total_duration_ns",
               "load_duration_ns", "prompt_eval_duration_ns", "eval_duration_ns", "done_reason",
               "thinking_observed", "model_digest", "user", "answer", "error"]
    with (out / "metrics.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for record in evidence["records"]:
            result = record.get("result", {})
            final = result.get("final", {})
            count, ns = final.get("eval_count"), final.get("eval_duration")
            row = {field: record.get(field, "") for field in columns}
            row.update(elapsed_s=result.get("elapsed_s", ""), ttft_s=result.get("ttft_s", ""),
                       thinking_observed=result.get("thinking_observed", ""),
                       model_digest=evidence.get("model_before", {}).get("digest", ""),
                       answer=result.get("content", ""),
                       tokens_per_s=count * 1e9 / ns if count is not None and ns else "")
            for field in ("prompt_eval_count", "eval_count", "done_reason"):
                row[field] = final.get(field, "")
            for field in ("total_duration", "load_duration", "prompt_eval_duration", "eval_duration"):
                row[field + "_ns"] = final.get(field, "")
            writer.writerow(row)
    # Never replace a user's existing subjective scores on incremental writes.
    score_path = out / "scores-user.csv"
    if not score_path.exists():
        fields = ["condition", "scenario_id", "scenario_name", "personality_visible"] + list(SCORE_FIELDS) + ["notes"]
        with score_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for condition in CONDITIONS:
                for scenario in scenarios:
                    writer.writerow({"condition": condition, "scenario_id": scenario["id"],
                                     "scenario_name": scenario["name"]})
    lines = ["# P1 actual personality baseline", "", f"Character: {evidence['character']['display_name']}",
             f"Started UTC: {evidence['started_utc']}", f"Status: {evidence['status']}",
             f"Model: `{evidence['settings']['model']}`", f"Digest: `{evidence.get('model_before', {}).get('digest', 'unavailable')}`",
             "", "Subjective scores are deliberately blank. The user is the primary judge.",
             "Rate each of the five criteria from 1–5 in scores-user.csv; personality_visible is yes/no.",
             "Each multi-turn scenario is scored as one whole conversation. Nothing here claims the character-quality target passed.",
             "", "## Measured text inference", "", "```json", json.dumps(evidence.get("summary", {}), indent=2), "```",
             "", "TTFT is time from HTTP request to first nonempty visible text chunk, only measured with --stream.",
             "A nonstream run leaves TTFT empty. These timings are not microphone-to-audio latency.",
             "Warmup is saved separately and excluded from summaries. Scenario order is fixed; condition order alternates.",
             "Fixed seed/config enables comparison but does not guarantee bit-for-bit output across hardware or service versions.",
             "", "## Actual replies", ""]
    for condition in CONDITIONS:
        lines.extend([f"### {condition}", ""])
        for record in evidence["records"]:
            if record["condition"] != condition:
                continue
            lines.extend([f"#### {record['scenario_id']} {record['scenario_name']} — turn {record['turn']}", "",
                          "User: " + record["user"], ""])
            if record["status"] == "ok":
                lines.extend(["Character: " + record["result"]["content"], ""])
            else:
                lines.extend(["ERROR: " + record.get("error", "unknown"), ""])
    if evidence.get("fatal_error"):
        lines.extend(["## Error", "", evidence["fatal_error"], ""])
    (out / "responses.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    args_parser = parser("Run P1 personality experiment: configured scenarios x 2 prompt conditions.")
    args_parser.add_argument("--scenarios", type=Path, default=ROOT / "experiments/personality/scenarios.json")
    args_parser.add_argument("--output", type=Path)
    args_parser.add_argument("--stream", action="store_true", help="Measure visible-text TTFT using NDJSON streaming")
    args_parser.add_argument("--no-warmup", action="store_true")
    args = args_parser.parse_args(argv)
    settings = load_settings(args)
    card = load_card(args.character)
    scenarios = read_json(args.scenarios)["scenarios"]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = args.output or ROOT / ".local/personality" / stamp
    if out.exists() and any(out.iterdir()):
        print("Output folder already contains files. Choose a new folder to preserve earlier evidence.", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    evidence = {"schema_version": 1, "stage": "P1", "status": "running", "started_utc": now(),
                "runtime": {"python": sys.version, "platform": platform.platform()},
                "character": card, "character_sha256": file_sha256(args.character),
                "scenarios_sha256": file_sha256(args.scenarios), "scenarios": scenarios,
                "settings_file_sha256": file_sha256(args.settings), "settings": settings,
                "stream": args.stream, "think": False, "records": [],
                "prompt_conditions": {c: system_prompt(card, c) for c in CONDITIONS},
                "scoring": "Unscored: human ratings required; no fabricated quality score."}
    client = OllamaClient(settings["endpoint"], settings["timeout_s"])
    write_outputs(out, evidence, scenarios)
    try:
        evidence["ollama_version"] = client.json_request("/api/version")
        evidence["model_before"] = client.model_identity(settings["model"])
        evidence["model_show"] = client.json_request("/api/show", {"model": settings["model"], "runner": settings["runner"]})
        if not args.no_warmup:
            warm_messages = [{"role": "user", "content": "Reply with the single English word ready."}]
            warm_options = dict(settings["options"], num_predict=12)
            warm_result = client.chat(settings["model"], warm_messages, warm_options,
                                      **request_kwargs(settings, args.stream))
            evidence["warmup"] = {"payload": client.chat_payload(settings["model"], warm_messages, warm_options,
                                **request_kwargs(settings, args.stream)), "result": asdict(warm_result)}
        # Alternate prompt-condition order to reduce a constant first/second-position bias.
        for index, scenario in enumerate(scenarios):
            conditions = CONDITIONS if index % 2 == 0 else tuple(reversed(CONDITIONS))
            for condition in conditions:
                conversation = Conversation(system_prompt(card, condition))
                for turn_number, template in enumerate(scenario["turns"], 1):
                    user_text = template.format_map(card["variables"])
                    messages = conversation.request_messages(user_text)
                    record = {"condition": condition, "scenario_id": scenario["id"], "scenario_name": scenario["name"],
                              "turn": turn_number, "user": user_text, "requested_utc": now(), "status": "pending",
                              "payload": client.chat_payload(settings["model"], messages, settings["options"],
                                                             **request_kwargs(settings, args.stream))}
                    try:
                        result = client.chat(settings["model"], messages, settings["options"],
                                             **request_kwargs(settings, args.stream))
                        record["result"] = asdict(result)
                        record["status"] = "ok"
                        conversation.accept(user_text, result.content)
                        print(f"{condition} {scenario['id']}/{turn_number}: {result.elapsed_s:.2f}s", flush=True)
                    except OllamaError as exc:
                        record["status"] = "error"
                        record["error"] = str(exc)
                        print(f"{condition} {scenario['id']}/{turn_number}: ERROR {exc}", flush=True)
                    evidence["records"].append(record)
                    evidence["summary"] = summary(evidence["records"])
                    write_outputs(out, evidence, scenarios)
                    if record["status"] != "ok":
                        # Do not pretend later A10 replies contain a missing earlier answer.
                        break
        evidence["model_after"] = client.model_identity(settings["model"])
        evidence["digest_unchanged"] = evidence["model_before"]["digest"] == evidence["model_after"]["digest"]
        if not evidence["digest_unchanged"]:
            raise OllamaError("Model tag digest changed during benchmark; this comparison is invalid.")
        expected = 2 * sum(len(scenario["turns"]) for scenario in scenarios)
        all_ok = len(evidence["records"]) == expected and all(r["status"] == "ok" for r in evidence["records"])
        evidence["expected_requests"] = expected
        evidence["status"] = "inference_complete_unscored" if all_ok else "incomplete"
    except (OllamaError, OSError, ValueError) as exc:
        evidence["status"] = "error"
        evidence["fatal_error"] = str(exc)
        print(str(exc), file=sys.stderr)
    except KeyboardInterrupt:
        evidence["status"] = "interrupted"
        print("Interrupted; completed records are retained.", file=sys.stderr)
    evidence["finished_utc"] = now()
    evidence["summary"] = summary(evidence["records"])
    write_outputs(out, evidence, scenarios)
    print(f"Evidence saved: {out}")
    return 0 if evidence["status"] == "inference_complete_unscored" else 1


if __name__ == "__main__":
    raise SystemExit(main())
