"""
LLM Client — handles all communication with the Gemini API.
Includes retry logic and fallback responses.
"""
import json
import logging
import traceback
import google.generativeai as genai
from config import settings
from orchestrator.prompt_manager import SYSTEM_PROMPT, build_user_prompt, build_retry_prompt
from orchestrator.output_validator import validate_llm_output

logger = logging.getLogger(__name__)

# Configure Gemini
genai.configure(api_key=settings.GEMINI_API_KEY)

# Try to initialize the model — use gemini-1.5-flash as reliable fallback
MODEL_NAME = "gemini-3.1-flash-lite-preview"
FALLBACK_MODEL_NAME = "gemini-2.5-flash"

model = None

def _init_model(name: str):
    """Initialize the Gemini model with the given name."""
    global model
    try:
        model = genai.GenerativeModel(
            model_name=name,
            system_instruction=SYSTEM_PROMPT,
            generation_config={
                "temperature": 0.7,
                "max_output_tokens": 1024,
            }
        )
        logger.info(f"Gemini model initialized: {name}")
    except Exception as e:
        logger.error(f"Failed to init model '{name}': {e}")
        model = None

# Try primary, then fallback
_init_model(MODEL_NAME)
if model is None:
    logger.warning(f"Primary model failed, trying fallback: {FALLBACK_MODEL_NAME}")
    _init_model(FALLBACK_MODEL_NAME)


FALLBACK_RESPONSE = {
    "reasoning": "LLM API call failed. Using fallback response to keep the user informed.",
    "actions": [
        {
            "type": "speech_output",
            "text": "I'm having a moment of difficulty processing. Could you please repeat that?",
            "language": "en"
        }
    ]
}


async def call_llm(context_bundle: dict, max_retries: int = 2) -> dict:
    """
    Send the Context Bundle to Gemini and get validated structured actions back.
    """
    if model is None:
        logger.error("No Gemini model available!")
        return FALLBACK_RESPONSE

    user_prompt = build_user_prompt(context_bundle)
    
    for attempt in range(max_retries + 1):
        try:
            logger.info(f"Calling Gemini API (attempt {attempt + 1}/{max_retries + 1})")
            
            response = model.generate_content(user_prompt)
            raw_text = response.text.strip()
            
            logger.info(f"Raw LLM response: {raw_text[:500]}")
            
            # Strip markdown code fences if present
            if raw_text.startswith("```"):
                lines = raw_text.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                raw_text = "\n".join(lines).strip()
            
            # Parse JSON
            try:
                parsed = json.loads(raw_text)
            except json.JSONDecodeError as e:
                logger.warning(f"JSON parse error: {e}\nRaw text: {raw_text[:300]}")
                if attempt < max_retries:
                    user_prompt = build_retry_prompt(f"Invalid JSON: {e}", raw_text)
                    continue
                else:
                    return FALLBACK_RESPONSE
            
            # Validate structure
            is_valid, error_msg = validate_llm_output(parsed)
            if is_valid:
                logger.info("LLM output validated successfully")
                return parsed
            else:
                logger.warning(f"Validation failed: {error_msg}")
                if attempt < max_retries:
                    user_prompt = build_retry_prompt(error_msg, raw_text)
                    continue
                else:
                    return FALLBACK_RESPONSE
                    
        except Exception as e:
            logger.error(f"Gemini API error (attempt {attempt + 1}): {e}")
            logger.error(traceback.format_exc())
            if attempt < max_retries:
                continue
            else:
                return FALLBACK_RESPONSE
    
    return FALLBACK_RESPONSE
