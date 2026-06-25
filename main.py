from fastapi import FastAPI
from fastapi.responses import Response
from twilio.twiml.voice_response import VoiceResponse

def say_something(message: str = "Hello from Twlilio!"):
    response = VoiceResponse()
    response.say(message)

    return str(response)

app = FastAPI()

@app.get("/health")
async def health():
    return {"message": "healthy"}

@app.get("/voice")
async def voice():
    return Response(content=say_something(), media_type="application/xml")
