"""Lambda de chat: recibe el historial de mensajes y responde con Claude en Amazon Bedrock.

Entrada (POST JSON):  {"messages": [{"role": "user"|"assistant", "content": "texto"}, ...]}
Salida (JSON):        {"reply": "texto"}  o  {"error": "mensaje"}
"""

import base64
import json
import logging
import os

import anthropic
from anthropic import AnthropicBedrockMantle

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MODEL_ID = os.environ.get("MODEL_ID", "anthropic.claude-opus-5-5")
EFFORT = os.environ.get("EFFORT", "low")  # low | medium | high
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "4096"))
MAX_HISTORY = int(os.environ.get("MAX_HISTORY", "20"))  # mensajes que se envían al modelo
MAX_CHARS = int(os.environ.get("MAX_CHARS", "4000"))  # límite por mensaje del usuario
SYSTEM_PROMPT = os.environ.get(
    "SYSTEM_PROMPT",
    "Eres un asistente útil y amable. Responde en el idioma del usuario, de forma clara y concisa.",
)

# La región sale de la variable que Lambda define automáticamente.
# Las credenciales son las del rol IAM de la función.
client = AnthropicBedrockMantle(aws_region=os.environ.get("AWS_REGION", "us-east-1"))


def _response(status, body):
    # Los encabezados CORS los añade API Gateway (ver template.yaml).
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, ensure_ascii=False),
    }


def _validate(payload):
    messages = payload.get("messages") if isinstance(payload, dict) else None
    if not isinstance(messages, list) or not messages:
        raise ValueError("Se esperaba un campo 'messages' con al menos un mensaje.")

    clean = []
    for m in messages[-MAX_HISTORY:]:
        if not isinstance(m, dict) or m.get("role") not in ("user", "assistant"):
            raise ValueError("Cada mensaje necesita 'role' igual a 'user' o 'assistant'.")
        content = m.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Cada mensaje necesita un 'content' de texto no vacío.")
        if m["role"] == "user" and len(content) > MAX_CHARS:
            raise ValueError(f"El mensaje supera el límite de {MAX_CHARS} caracteres.")
        clean.append({"role": m["role"], "content": content})

    # La API exige que la conversación empiece por el usuario y termine con el usuario.
    while clean and clean[0]["role"] != "user":
        clean.pop(0)
    if not clean or clean[-1]["role"] != "user":
        raise ValueError("El último mensaje debe ser del usuario.")
    return clean


def lambda_handler(event, context):
    method = (event.get("requestContext", {}).get("http", {}) or {}).get("method", "POST")
    if method == "OPTIONS":
        return _response(204, {})

    try:
        raw = event.get("body") or "{}"
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw).decode("utf-8")
        messages = _validate(json.loads(raw))
    except (ValueError, json.JSONDecodeError) as exc:
        return _response(400, {"error": str(exc)})

    try:
        response = client.messages.create(
            model=MODEL_ID,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            output_config={"effort": EFFORT},
            messages=messages,
        )
    except anthropic.RateLimitError:
        return _response(429, {"error": "Demasiadas solicitudes. Inténtalo de nuevo en un momento."})
    except anthropic.PermissionDeniedError:
        logger.exception("Permiso denegado en Bedrock")
        return _response(502, {"error": "La función no tiene acceso al modelo en Bedrock. Revisa el README."})
    except anthropic.APIStatusError as exc:
        logger.exception("Error de Bedrock: %s", exc.status_code)
        return _response(502, {"error": f"Error del servicio de IA ({exc.status_code})."})
    except anthropic.APIConnectionError:
        logger.exception("No se pudo conectar con Bedrock")
        return _response(504, {"error": "No se pudo contactar con el servicio de IA."})

    if response.stop_reason == "refusal":
        return _response(200, {"reply": "Lo siento, no puedo ayudar con esa solicitud."})

    text = "".join(block.text for block in response.content if block.type == "text").strip()
    if response.stop_reason == "max_tokens":
        text += "\n\n[Respuesta recortada por el límite de longitud]"

    logger.info(
        "tokens entrada=%s salida=%s", response.usage.input_tokens, response.usage.output_tokens
    )
    return _response(200, {"reply": text or "(sin respuesta)"})
