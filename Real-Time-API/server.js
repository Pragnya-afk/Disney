import express from "express";
import dotenv from "dotenv";
import path from "path";
import { fileURLToPath } from "url";

dotenv.config();

const app = express();
const port = process.env.PORT || 3000;

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

app.use(express.text({ type: ["application/sdp", "text/plain"] }));
app.use(express.static(path.join(__dirname, "public")));

app.post("/session", async (req, res) => {
  try {
    if (!process.env.OPENAI_API_KEY) {
      return res.status(500).send("Missing OPENAI_API_KEY in .env");
    }

    const fd = new FormData();
    fd.set("sdp", req.body);

    fd.set(
      "session",
      JSON.stringify({
        type: "realtime",
        model: "gpt-realtime",
        instructions:
          "You are a cinematic interactive storyteller. Keep responses immersive, clear, and conversational. Continue the scene naturally and remember prior messages in the session. Keep speaking in English",
        audio: {
          output: {
            voice: "marin"
          }
        }
      })
    );

    const response = await fetch("https://api.openai.com/v1/realtime/calls", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${process.env.OPENAI_API_KEY}`
      },
      body: fd
    });

    const text = await response.text();

    if (!response.ok) {
      console.error("OpenAI error:", text);
      return res.status(response.status).send(text);
    }

    res.set("Content-Type", "application/sdp");
    res.send(text);
  } catch (error) {
    console.error(error);
    res.status(500).send("Failed to create realtime session");
  }
});

app.listen(port, () => {
  console.log(`Server running at http://localhost:${port}`);
});