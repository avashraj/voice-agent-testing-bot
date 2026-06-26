import asyncio
import json
import os
import traceback
from pathlib import Path

import httpx
import websockets
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

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise Exception("add openai api key to .env")

RECORDINGS_DIR = Path("recordings")

REALTIME_MODEL = "gpt-realtime"
REALTIME_URL = f"wss://api.openai.com/v1/realtime?model={REALTIME_MODEL}"

SCENARIO_PROMPT = (
    "You are the PATIENT, and you placed this call to a medical clinic to "
    "schedule a follow-up appointment. The person you are speaking with is "
    "the clinic staff. Never act as the clinic or receptionist, even if they "
    "say things that sound like they expect you to. Always speak in English. "
    "Speak naturally and conversationally. Keep replies short. Wait for the "
    "other person to finish before responding."
)

def stream_twiml(ws_url: str):
    # Connect straight to the media stream; the bot handles the greeting.
    response = VoiceResponse()
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
    return Response(content=stream_twiml(ws_url), media_type="application/xml")

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


async def configure_realtime(openai_ws):
    # GA schema. Both legs are pcmu (g711 u-law) 8kHz -> no transcoding.
    await openai_ws.send(json.dumps({
        "type": "session.update",
        "session": {
            "type": "realtime",
            "instructions": SCENARIO_PROMPT,
            "audio": {
                "input": {
                    "format": {"type": "audio/pcmu"},
                    "turn_detection": {"type": "server_vad"},
                },
                "output": {
                    "format": {"type": "audio/pcmu"},
                    "voice": "marin",
                },
            },
        },
    }))


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("Twilio /ws accepted, connecting to OpenAI realtime...")

    try:
        async with websockets.connect(
            REALTIME_URL,
            additional_headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
            },
        ) as openai_ws:
            print("OpenAI realtime connected.")
            await configure_realtime(openai_ws)

            # Shared mutable state between the two pump tasks.
            state = {"stream_sid": None, "response_active": False}

            async def twilio_to_openai():
                # Twilio media frames -> OpenAI input audio buffer.
                try:
                    while True:
                        data = await websocket.receive_text()
                        message = json.loads(data)
                        event = message["event"]
                        if event == "start":
                            state["stream_sid"] = message["start"]["streamSid"]
                            print(f"start streamSid={state['stream_sid']}")
                        elif event == "media":
                            await openai_ws.send(json.dumps({
                                "type": "input_audio_buffer.append",
                                "audio": message["media"]["payload"],
                            }))
                        elif event == "stop":
                            print("STOP")
                            break
                except WebSocketDisconnect:
                    print("Twilio WebSocket closed")
                finally:
                    await openai_ws.close()

            async def openai_to_twilio():
                # OpenAI audio deltas -> Twilio media; handle barge-in.
                async for raw in openai_ws:
                    event = json.loads(raw)
                    etype = event.get("type")
                    if etype == "response.created":
                        state["response_active"] = True
                    elif etype == "response.done":
                        state["response_active"] = False
                    elif etype == "response.output_audio.delta":
                        await websocket.send_text(json.dumps({
                            "event": "media",
                            "streamSid": state["stream_sid"],
                            "media": {"payload": event["delta"]},
                        }))
                    elif etype == "input_audio_buffer.speech_started":
                        # Barge-in: caller started talking, flush queued bot audio.
                        await websocket.send_text(json.dumps({
                            "event": "clear",
                            "streamSid": state["stream_sid"],
                        }))
                        if state["response_active"]:
                            await openai_ws.send(json.dumps({"type": "response.cancel"}))
                    elif etype == "error":
                        print(f"realtime error: {event}")

            # First task to finish (e.g. caller hangs up) cancels the other so
            # the socket tears down instead of hanging on the live task.
            tasks = [
                asyncio.create_task(twilio_to_openai()),
                asyncio.create_task(openai_to_twilio()),
            ]
            done, pending = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            print("call torn down")
    except Exception:
        print("=== /ws handler crashed (this is what plays the Twilio app error) ===")
        traceback.print_exc()
        raise
