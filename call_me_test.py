import os
from twilio.rest import Client
from dotenv import load_dotenv
load_dotenv()

account_sid = os.getenv("TWILIO_ACCOUNT_SID")
auth_token = os.getenv("TWILIO_AUTH_TOKEN")
phone_number = os.getenv("TWILIO_PHONE_NUMBER", "")
url = os.getenv("URL")
my_number = os.getenv("MY_NUMBER", "")

client = Client(account_sid, auth_token)

call = client.calls.create(
    from_=phone_number,
    to=my_number,
    url=url
)

print(call.sid)
