from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from anthropic import Anthropic, APIError
import os
import subprocess
import shutil

app = FastAPI(title="Browser-Agent-Bob API Bridge")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_origin_regex=r"chrome-extension://.*",
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    api_key: str
    model: str = "claude-sonnet-4-6"
    provider: str = "anthropic"


class ChatResponse(BaseModel):
    response: str
    input_tokens: int = 0
    output_tokens: int = 0


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message is required")
    if not req.api_key.strip():
        raise HTTPException(status_code=400, detail="api_key is required")

    provider = req.provider.lower()

    if provider == "ibm":
        result = handle_bob(req)
    elif provider == "anthropic":
        result = handle_anthropic(req)
    elif provider == "openai":
        result = handle_openai(req)
    elif provider == "google":
        result = handle_google(req)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    print(f"[api_bridge] provider={provider} response_dict={result.dict()}", flush=True)
    return result


def handle_bob(req: ChatRequest):
    bob_cmd = shutil.which("bob") or shutil.which("bob-shell")
    if not bob_cmd:
        raise HTTPException(
            status_code=500,
            detail="Please install Bob Shell from https://ibm.biz/get-bob to use IBM Bob",
        )

    env = {**os.environ, "BOBSHELL_API_KEY": req.api_key}
    cmd = [
        bob_cmd,
        "--accept-license",
        "--chat-mode", "ask",
        "--hide-intermediary-output",
        "--output-format", "text",
        req.message,
    ]

    try:
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Bob Shell timed out.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bob Shell error: {str(e)}")

    output = (result.stdout or "").strip()
    if not output:
        detail = (result.stderr or "").strip() or "Bob Shell returned no response."
        raise HTTPException(status_code=502, detail=f"Bob Shell error: {detail}")
    input_tokens = int(len(req.message.split()) * 1.3)
    output_tokens = int(len(output.split()) * 1.3)
    return ChatResponse(response=output, input_tokens=input_tokens, output_tokens=output_tokens)


def handle_anthropic(req: ChatRequest):
    try:
        client = Anthropic(api_key=req.api_key)
        result = client.messages.create(
            model=req.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": req.message}],
        )
        text = "".join(b.text for b in result.content if getattr(b, "type", None) == "text")
        return ChatResponse(
            response=text.strip(),
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
        )
    except APIError as e:
        raise HTTPException(status_code=502, detail=f"Anthropic error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def handle_openai(req: ChatRequest):
    try:
        import openai
        client = openai.OpenAI(api_key=req.api_key)
        result = client.chat.completions.create(
            model=req.model,
            messages=[{"role": "user", "content": req.message}],
            max_tokens=1024,
        )
        return ChatResponse(
            response=result.choices[0].message.content.strip(),
            input_tokens=result.usage.prompt_tokens,
            output_tokens=result.usage.completion_tokens,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"OpenAI error: {str(e)}")


def handle_google(req: ChatRequest):
    try:
        import google.generativeai as genai
        genai.configure(api_key=req.api_key)
        model = genai.GenerativeModel(req.model)
        result = model.generate_content(req.message)
        return ChatResponse(
            response=result.text.strip(),
            input_tokens=result.usage_metadata.prompt_token_count,
            output_tokens=result.usage_metadata.candidates_token_count,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Google error: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
