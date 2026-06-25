import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from twilio.twiml.voice_response import Connect, VoiceResponse

load_dotenv()

ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
if not ACCOUNT_SID:
    raise Exception("add account sid to .env")

AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
if not AUTH_TOKEN:
    raise Exception("add auth token to .env")

RECORDINGS_DIR = Path("recordings")

def say_something(
    ws_url: str,
    message: str = "Hello from Twlilio! This is FastAPI!",
    ):
    response = VoiceResponse()
    response.say(message)
    connect = Connect()
    connect.stream(url=ws_url)
    response.append(connect)
    return str(response)

app = FastAPI()

@app.get("/health")
async def health():
    return {"message": "healthy"}

@app.api_route("/voice", methods=["GET", "POST"])
async def voice():
    ws_url = "wss://alica-bridlewise-catatonically.ngrok-free.dev/ws"
    return Response(content=say_something(ws_url), media_type="application/xml")

@app.post("/recording")
async def recording(
    RecordingSid: str = Form(...),
    RecordingUrl: str = Form(...),
    RecordingStatus: str = Form(...),
    CallSid: str = Form(...),
):
    # Twilio fires this when the dual-channel recording is ready.
    if RecordingStatus != "completed":
        print(f"recording {RecordingSid} status={RecordingStatus}")
        return Response(status_code=204)

    RECORDINGS_DIR.mkdir(exist_ok=True)
    out_path = RECORDINGS_DIR / f"{CallSid}.mp3"
    async with httpx.AsyncClient() as http:
        # append .mp3 to the media URL; auth with Twilio creds
        resp = await http.get(f"{RecordingUrl}.mp3", auth=(ACCOUNT_SID, AUTH_TOKEN))
        resp.raise_for_status()
        out_path.write_bytes(resp.content)
    print(f"saved recording {out_path} ({len(resp.content)} bytes)")
    return Response(status_code=204)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    stream_sid = None
    frames = 0
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            event = message["event"]
            if event == "connected":
                print("connected")
            elif event == "start":
                stream_sid = message["start"]["streamSid"]
                print(f"start streamSid={stream_sid}")
            elif event == "media":
                frames += 1
                # echo: send inbound audio straight back down the socket
                await websocket.send_text(json.dumps({
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": message["media"]["payload"]},
                }))
            elif event == "stop":
                print(f"STOP frames={frames}")
                break
            else:
                print(f"unknown event: {event}")
    except WebSocketDisconnect:
        print(f"WebSocket connection closed frames={frames}")
