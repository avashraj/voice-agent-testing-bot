import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from twilio.twiml.voice_response import Connect, VoiceResponse

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

#TODO: Make a web socket
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
