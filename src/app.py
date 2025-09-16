import os
from flask import Flask, request, Response, jsonify
from twilio.twiml.voice_response import VoiceResponse, Gather
from dotenv import load_dotenv
from src.tools.google_tasks import create_task

load_dotenv()
app = Flask(__name__)


def _split_items(s: str):
    raw = [x.strip(" .;-") for x in s.replace("\n", ",").split(",")]
    return [x for x in raw if x and len(x) > 1]


TOKEN = os.getenv("CALL_TRIGGER_TOKEN", "")


def _authorized(req) -> bool:
    # accept either header or query param
    hdr = req.headers.get("X-Trigger-Token", "")
    qp = req.args.get("token", "")
    return (hdr and hdr == TOKEN) or (qp and qp == TOKEN)


@app.get("/")
def health():
    return "OK", 200


@app.route("/voice", methods=["GET", "POST"])
def voice():
    vr = VoiceResponse()
    g = Gather(
        input="speech",
        language="en-US",
        speech_timeout="auto",
        action="/capture",
        method="POST",
    )
    g.say(
        "Good morning. What are your tasks for today? \
            Speak them as a list, pausing between items."
    )
    vr.append(g)
    vr.say("I didn't catch that. We'll try again later. Goodbye.")
    return Response(str(vr), mimetype="application/xml")


@app.post("/capture")
def capture():
    transcript = request.form.get("SpeechResult", "") or ""
    items = _split_items(transcript)
    made = 0
    for t in items:
        try:
            create_task(title=t)
            made += 1
        except Exception as e:
            print("Create failed:", t, e)

    vr = VoiceResponse()
    if made:
        vr.say(f"I captured {made} task{'s' if made != 1 else ''}. Goodbye.")
    else:
        vr.say("I couldn't capture any tasks. Goodbye.")
    return Response(str(vr), mimetype="application/xml")


@app.post("/call")
def call_me_now():
    if TOKEN and not _authorized(request):
        return jsonify({"error": "unauthorized"}), 401

    # Quick manual trigger to make Twilio ring you
    from twilio.rest import Client

    sid = os.environ["TWILIO_ACCOUNT_SID"]
    tok = os.environ["TWILIO_AUTH_TOKEN"]
    tw_from = os.environ["TWILIO_NUMBER"]
    you = os.environ["YOUR_NUMBER"]
    client = Client(sid, tok)
    call = client.calls.create(
        to=you,
        from_=tw_from,
        url=f"{request.url_root.strip('/')}/voice",
        method="POST"
    )
    return jsonify({"status": "started", "sid": call.sid})
