import os
from twilio.rest import Client
from dotenv import load_dotenv
load_dotenv()

account_sid = os.getenv("TWILIO_ACCOUNT_SID")
auth_token = os.getenv("TWILIO_AUTH_TOKEN")
phone_number = os.getenv("TWILIO_PHONE_NUMBER", "")
url = os.getenv("URL")
recording_callback = os.getenv("RECORDING_CALLBACK_URL")
to_number = os.getenv("TARGET_NUMBER")
if not to_number:
    raise Exception("add number to .env")

client = Client(account_sid, auth_token)

call = client.calls.create(
    from_=phone_number,
    to=to_number,
    url=url,
    time_limit=120,
    record=True,
    recording_channels="dual",
    recording_status_callback=recording_callback,
    recording_status_callback_event=["completed"],
)

print(call.sid)
