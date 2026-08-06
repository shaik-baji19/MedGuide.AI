import requests
from config import (
    MISTRAL_API_KEY, MISTRAL_ENDPOINT, MISTRAL_MODEL,
    HUGGINGFACE_API_KEY, HUGGINGFACE_ENDPOINT,
    OPENAI_API_KEY, OPENAI_ENDPOINT, OPENAI_MODEL
)

def call_ai(messages, max_tokens=2048):
    """
    Unified AI caller with fallback:
    Mistral → Hugging Face → OpenAI.
    """
    # Increased max_tokens significantly to prevent responses from cutting off
    error_log = []

    # 1. Mistral
    try:
        headers = {"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": MISTRAL_MODEL,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": max_tokens
        }
        resp = requests.post(MISTRAL_ENDPOINT, json=payload, headers=headers, timeout=30)
        
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        else:
            error_log.append(f"Mistral Error (Code {resp.status_code}): {resp.text}")
            
    except Exception as e:
        error_log.append(f"Mistral network error: {str(e)}")

    # 2. Hugging Face
    if HUGGINGFACE_API_KEY:
        try:
            prompt = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
            headers = {"Authorization": f"Bearer {HUGGINGFACE_API_KEY}"}
            payload = {
                "inputs": prompt,
                "parameters": {
                    "max_new_tokens": max_tokens,
                    "temperature": 0.7,
                    "return_full_text": False
                }
            }
            resp = requests.post(HUGGINGFACE_ENDPOINT, json=payload, headers=headers, timeout=60)
            
            if resp.status_code == 200:
                return resp.json()[0]["generated_text"].strip()
            else:
                error_log.append(f"Hugging Face Error (Code {resp.status_code}): {resp.text}")
                
        except Exception as e:
            error_log.append(f"Hugging Face network error: {str(e)}")
    else:
        error_log.append("Hugging Face skipped: No API Key provided.")

    # 3. OpenAI
    if OPENAI_API_KEY:
        try:
            headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
            payload = {
                "model": OPENAI_MODEL,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": max_tokens
            }
            resp = requests.post(OPENAI_ENDPOINT, json=payload, headers=headers, timeout=30)
            
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
            else:
                error_log.append(f"OpenAI Error (Code {resp.status_code}): {resp.text}")
                
        except Exception as e:
            error_log.append(f"OpenAI network error: {str(e)}")
    else:
        error_log.append("OpenAI skipped: No API Key provided.")

    # 4. Return the ACTUAL error logs to the chat UI
    debug_message = "⚠️ AI Debug Logs:\n\n" + "\n\n".join(error_log)
    return debug_message