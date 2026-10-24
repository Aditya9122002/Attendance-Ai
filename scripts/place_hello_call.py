"""Place one test call that only says hello, to prove the phone connection works.

Usage (from the project root, with the app running and a public tunnel open):
  uv run python scripts/place_hello_call.py --to +91XXXXXXXXXX

Needs TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER and PUBLIC_BASE_URL in .env.
Call only your own verified number. The auth token is never printed.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.telephony import TelephonyNotConfigured, place_hello_call  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to", required=True, help="your own verified number, like +91...")
    args = parser.parse_args()

    input(f"This will place a real call to {args.to}. Press Enter to continue, Ctrl+C to stop. ")
    try:
        sid = place_hello_call(get_settings(), args.to)
    except (ValueError, TelephonyNotConfigured) as exc:
        print(f"Not placed: {exc}")
        return 1
    print(f"Call requested. Twilio call SID: {sid}")
    print("Your phone should ring in a few seconds. Check the Twilio console if it does not.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
