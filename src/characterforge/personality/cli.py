"""A small P1 text demo; deliberately no voice, GUI, or durable memory."""

from dataclasses import asdict
from datetime import datetime
import sys

from characterforge.llm.ollama import OllamaClient, OllamaError
from .card import ROOT, Conversation, load_card, system_prompt
from .benchmark import load_settings, now, parser, request_kwargs, write_json


def main(argv=None) -> int:
    args_parser = parser("CharacterForge P1 English text chat")
    args_parser.add_argument("--condition", choices=("rules_only", "rules_plus_background"),
                             default=None, help="Override the profile default prompt condition")
    args_parser.add_argument("--once", help="One noninteractive reply; useful for smoke verification")
    args = args_parser.parse_args(argv)
    settings = load_settings(args)
    condition = args.condition or settings.get("personality_condition", "rules_plus_background")
    if condition not in ("rules_only", "rules_plus_background"):
        args_parser.error("The profile personality_condition must be rules_only or rules_plus_background.")
    card = load_card(args.character)
    client = OllamaClient(settings["endpoint"], settings["timeout_s"])
    try:
        identity = client.model_identity(settings["model"])
    except OllamaError as exc:
        print(f"Local model is unavailable: {exc}\nStart the project Ollama service first.", file=sys.stderr)
        return 1
    conversation = Conversation(system_prompt(card, condition))
    out = ROOT / ".local/text-chats" / (datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".json")
    out.parent.mkdir(parents=True, exist_ok=True)
    session = {"stage": "P1", "started_utc": now(), "character": card,
               "condition": condition, "settings": settings, "model_identity": identity, "events": []}
    print(f"CharacterForge P1 | {card['display_name']} | English text only")
    print("Type /quit to exit, /reset for a new conversation, /help for controls.")
    print("Recent chat context only; older turns beyond 8 are dropped. This is not long-term memory.")
    print(f"Private transcript: {out}\n")
    exit_code = 0
    try:
        while True:
            if args.once is not None:
                text = args.once
                print("You: " + text)
            else:
                try:
                    text = input("You: ").strip()
                except EOFError:
                    break
            if not text:
                if args.once is not None:
                    break
                continue
            if text.lower() == "/quit":
                break
            if text.lower() == "/help":
                print("/quit: exit | /reset: clear current context | Ordinary English: talk to the character")
                continue
            if text.lower() == "/reset":
                conversation = Conversation(system_prompt(card, condition))
                session["events"].append({"type": "reset", "utc": now()})
                write_json(out, session)
                print("Current context cleared. Earlier text remains in the private transcript.\n")
                continue
            event = {"type": "turn", "utc": now(), "user": text}
            messages = conversation.request_messages(text)
            event["payload"] = client.chat_payload(settings["model"], messages, settings["options"],
                                                   **request_kwargs(settings, True))
            print("Character: ", end="", flush=True)
            try:
                result = client.chat(settings["model"], messages, settings["options"],
                                     on_text=lambda chunk: print(chunk, end="", flush=True),
                                     **request_kwargs(settings, True))
                first = f"{result.ttft_s:.2f}s" if result.ttft_s is not None else "unavailable"
                print(f"\n[{result.elapsed_s:.2f}s total; first text {first}]\n")
                event["result"] = asdict(result)
                conversation.accept(text, result.content)
                if len(conversation.messages) > 17:
                    conversation.messages = [conversation.messages[0]] + conversation.messages[-16:]
                    event["older_turns_dropped"] = True
                    print("[Older chat turns dropped from model context.]\n")
            except OllamaError as exc:
                event["error"] = str(exc)
                print(f"\nLocal model error: {exc}\nThe failed turn was not added to context.\n")
                exit_code = 1
            session["events"].append(event)
            write_json(out, session)
            if args.once is not None:
                break
    except KeyboardInterrupt:
        print("\nChat stopped.")
    session["finished_utc"] = now()
    write_json(out, session)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
