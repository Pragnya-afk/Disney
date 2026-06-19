## Run Real-Time API 

## run js code
In terminal : npm start
open http://localhost:3000/

## run python code 
cd Real-Time-API
source venv/bin/activate
python3 server.py

## Modify 
- server.js:
his is your base prompt
→ It defines the character/personality for the entire session. so to change overall behaviour edit this string
``` json
fd.set(
  "session",
  JSON.stringify({
    type: "realtime",
    model: "gpt-realtime",
    instructions:
      "You are a cinematic interactive storyteller. Keep responses immersive, clear, and conversational. Continue the scene naturally and remember prior messages in the session.",
```

Dynamic promp (what it says right now)
- index.html

``` json 
dc.send(JSON.stringify({
  type: "response.create",
  response: {
    instructions: "Introduce yourself as a realtime storytelling assistant in one short sentence."
  }
}));

```
This is a runtime instruction
→ It tells the model what to say at that moment -> ie control the story flow

 in terminal : ctrl c -> cancels it 