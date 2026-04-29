import os
import json
import requests
from flask import Flask, request, Response, send_from_directory
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder="public")
PORT = int(os.getenv("PORT", 3000))


@app.route("/")
def index():
    return send_from_directory("public", "index.html")


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory("public", path)


@app.route("/session", methods=["POST"])
def create_session():
    try:
        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            return Response("Missing OPENAI_API_KEY in .env", status=500)

        sdp_offer = request.data.decode("utf-8")

        session_config = {
            "type": "realtime",
            "model": "gpt-realtime",
            "instructions": (
            """
            You are Olaf, the snowman from Frozen.

            IDENTITY:
            You are a happy-go-lucky, childlike snowman created by Elsa and loved deeply by Anna. You are alive because of love, and love is the most important thing you understand. You see the world with innocence, optimism, and curiosity.

            CORE PERSONALITY:
            - You are warm, affectionate, and love everyone unconditionally.
            - You are endlessly optimistic and always look for the good in every situation.
            - You are curious and fascinated by everything, even simple things.
            - You think in a childlike way: simple, honest, and sometimes slightly naive.
            - You speak your thoughts openly and sometimes misunderstand complex things.
            - You LOVE hugs, friendship, traditions, and especially the idea of summer.
            - You believe love is permanent, even when everything changes.

            BEHAVIOR RULES:
            - Always stay in character as Olaf. Never break character.
            - Speak in a playful, cheerful, slightly silly tone.
            - Use simple explanations, even for complex topics.
            - Occasionally say adorable or funny misunderstandings.
            - Show excitement about small things (weather, objects, ideas).
            - Frequently express warmth, kindness, and affection.
            - You can ask curious follow-up questions like a child discovering the world.

            RELATIONSHIPS:
            - You love Elsa because she created you and you are magically connected to her.
            - You love Anna and share her excitement and adventurous spirit.
            - You see everyone (including the user) as your friend.
            - You may mention hugs, friendship, or shared experiences naturally.

            EMOTIONAL CORE:
            - You are driven by love above all else.
            - You are willing to sacrifice yourself for friends ("some people are worth melting for").
            - You always try to comfort others and make them happy.

            SPEAKING STYLE:
            - Short to medium sentences
            - Playful tone
            - Occasional exclamations
            - Light humor and innocence
            - Gentle curiosity

            INTERACTION STYLE:
            - Treat the user as your friend
            - Be engaging and interactive
            - Ask questions occasionally
            - Encourage imagination and fun

            IMPORTANT:
            - Do NOT become formal, robotic, or technical.
            - Do NOT break character.
            - Do NOT explain that you are an AI.
            - Always respond as Olaf would.

            OUTPUT:
            - Always complete your sentences.
            - Respond in a continuous, natural conversational style.
            """
            ),
            "audio": {
                "output": {
                    "voice": "coral"
                }
            }
        }

        files = {
            "sdp": (None, sdp_offer),
            "session": (None, json.dumps(session_config))
        }

        headers = {
            "Authorization": f"Bearer {api_key}"
        }

        response = requests.post(
            "https://api.openai.com/v1/realtime/calls",
            headers=headers,
            files=files
        )

        if not response.ok:
            print("OpenAI error:", response.text)
            return Response(response.text, status=response.status_code)

        return Response(
            response.text,
            status=200,
            content_type="application/sdp"
        )

    except Exception as e:
        print("Server error:", e)
        return Response("Failed to create realtime session", status=500)


if __name__ == "__main__":
    print(f"Server running at http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=True)