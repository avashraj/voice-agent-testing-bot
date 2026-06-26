"""Suite runner. For each scenario, place its call leg(s) against the clinic bot,
wait for the transcript file the server writes on hangup, then (if the judge from
#9 is available) score it. One scenario at a time, flat files only.

Usage:
    uv run python run_suite.py                              # whole suite
    uv run python run_suite.py --only 01-happy-path         # one scenario
    uv run python run_suite.py --only 01-happy-path 05-broken-leg   # a subset
    uv run python run_suite.py --timeout 180                # per-call wait (sec)
"""

import argparse
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from twilio.rest import Client

from scenarios import SCENARIOS, get_scenario

load_dotenv()

TRANSCRIPTS_DIR = Path("transcripts")
ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
FROM_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "")
TO_NUMBER = os.getenv("TARGET_NUMBER")
VOICE_URL = os.getenv("URL")  # the /voice webhook
RECORDING_CALLBACK = os.getenv("RECORDING_CALLBACK_URL")

# Server writes the transcript on call teardown as
# transcripts/<scenario_id>_leg<n>_<call_sid>.json (see main.write_transcript).
TIME_LIMIT = 120  # cap each call so it ends and the transcript lands

# Judge lands in #9; until then the runner just collects transcripts.
try:
    from judge import judge  # judge(scenario, transcripts) -> Verdict
except ImportError:
    judge = None


def transcript_path(scenario_id: str, leg: int, call_sid: str) -> Path:
    return TRANSCRIPTS_DIR / f"{scenario_id}_leg{leg}_{call_sid}.json"


def place_call(client: Client, scenario_id: str, leg: int) -> str:
    """Dial the clinic bot for one leg; return the Twilio call SID."""
    url = f"{VOICE_URL}?scenario={scenario_id}&leg={leg}"
    call = client.calls.create(
        from_=FROM_NUMBER,
        to=TO_NUMBER,
        url=url,
        time_limit=TIME_LIMIT,
        record=True,
        recording_channels="dual",
        recording_status_callback=RECORDING_CALLBACK,
        recording_status_callback_event=["completed"],
    )
    return call.sid


def wait_for_transcript(path: Path, timeout: int) -> bool:
    """Poll until the server writes the transcript file, or give up."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(2)
    return False


def run_scenario(client: Client, scenario, timeout: int) -> dict:
    """Place every leg in order; return a result dict for the report."""
    leg_paths = []
    for leg in range(len(scenario.calls)):
        print(f"[{scenario.id}] placing call leg {leg}...")
        call_sid = place_call(client, scenario.id, leg)
        path = transcript_path(scenario.id, leg, call_sid)
        print(f"[{scenario.id}] call {call_sid}; waiting for transcript...")
        if not wait_for_transcript(path, timeout):
            print(f"[{scenario.id}] ERROR: no transcript for leg {leg} before timeout")
            return {"scenario_id": scenario.id, "status": "error",
                    "reason": f"no transcript for leg {leg}", "transcripts": leg_paths}
        leg_paths.append(str(path))
        print(f"[{scenario.id}] leg {leg} transcript: {path}")

    result = {"scenario_id": scenario.id, "status": "ran", "transcripts": leg_paths}
    if judge is not None:
        verdict = judge(scenario, leg_paths)
        result.update({"status": "judged", "verdict": verdict})
    return result


def select_suite(only: list[str] | None) -> list:
    """Resolve --only ids (in the order given) to Scenarios, or the full suite."""
    if not only:
        return SCENARIOS
    suite = []
    for scenario_id in only:
        scenario = get_scenario(scenario_id)
        if not scenario:
            raise SystemExit(f"unknown scenario id: {scenario_id}")
        suite.append(scenario)
    return suite


def main():
    parser = argparse.ArgumentParser(description="Run the patient-bot scenario suite")
    parser.add_argument("--only", nargs="+", metavar="ID",
                        help="run only these scenario id(s), in order")
    parser.add_argument("--timeout", type=int, default=TIME_LIMIT + 30,
                        help="seconds to wait for each call's transcript")
    args = parser.parse_args()

    if not (ACCOUNT_SID and AUTH_TOKEN and TO_NUMBER and VOICE_URL):
        raise SystemExit("missing TWILIO creds / TARGET_NUMBER / URL in .env")

    suite = select_suite(args.only)

    client = Client(ACCOUNT_SID, AUTH_TOKEN)
    results = []
    for scenario in suite:
        results.append(run_scenario(client, scenario, args.timeout))

    print("\n=== suite summary ===")
    for r in results:
        print(f"{r['scenario_id']:20} {r['status']}")


if __name__ == "__main__":
    main()
