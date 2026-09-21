import logging
import json
import time
import os
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

from config import settings
from perception.asr_handler import ASRHandler
from modeling.temporal_decay import decay_user_state
from modeling.accessibility_policy import AccessibilityPolicy
from orchestrator.context_bundle import ContextBundleAssembler
from orchestrator.llm_client import call_llm
from session.session_manager import SessionManager

# Configure basic logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.PROJECT_NAME, version=settings.VERSION)

# Enable CORS for the frontend to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session manager
session_mgr = SessionManager()

# ─── Serve Frontend Static Files ───
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="css")
    app.mount("/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="js")
    logger.info(f"Serving frontend from: {FRONTEND_DIR}")
else:
    logger.warning(f"Frontend directory not found: {FRONTEND_DIR}")


@app.get("/")
async def root():
    """Serve the frontend index.html."""
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": f"Welcome to the {settings.PROJECT_NAME} Backend", "version": settings.VERSION}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session_id = f"session_{id(websocket)}"
    session = session_mgr.get_or_create(session_id)
    logger.info(f"WebSocket connected — session {session_id}")

    # Send initial kiosk screen state on connection
    init_payload = {
        "type": "kiosk_screen_update",
        "screen": session.get_kiosk_frontend()
    }
    await websocket.send_text(json.dumps(init_payload))
    
    try:
        while True:
            data_str = await websocket.receive_text()
            logger.info(f"Received: {data_str[:200]}")
            
            try:
                payload = json.loads(data_str)
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON: {data_str[:100]}")
                continue
            
            msg_type = payload.get("type")
            
            # ─── Handle user state updates from control panel sliders ───
            if msg_type == "user_state_update":
                state_data = payload.get("data", {})

                # Update canonical state.
                session.user_state.update_from_frontend(state_data)

                # Evaluate accessibility using the single deterministic policy.
                accessibility = AccessibilityPolicy.evaluate(
                    session.user_state
                )

                logger.info(
                    "User state updated: "
                    f"visual={session.user_state.visual_capability:.2f}, "
                    f"motor={session.user_state.motor_capability:.2f}, "
                    f"flags={session.user_state.behavioral_flags}, "
                    f"tremor={session.user_state.hand_tremor:.2f}, "
                    f"adaptation={accessibility['accessibility_level']}"
                )

                # Send the decision back to the web renderer.
                await websocket.send_text(json.dumps({
                    "type": "accessibility_update",
                    "decision": accessibility
                }))

                continue

            # ─── Handle empathetic proactive prompt logging ───
            if msg_type == "empathetic_prompt_logged":
                prompt_text = payload.get("text", "")
                session.add_assistant_prompt(prompt_text)
                logger.info(f"Empathetic prompt logged to conversation history: {prompt_text}")
                continue
            
            # ─── Handle kiosk mode switch ───
            if msg_type == "kiosk_mode_change":
                mode = payload.get("mode", "atm")
                session.set_kiosk_mode(mode)
                logger.info(f"Kiosk mode changed to: {mode}")
                # Send new screen to frontend
                screen_payload = {
                    "type": "kiosk_screen_update",
                    "screen": session.get_kiosk_frontend()
                }
                await websocket.send_text(json.dumps(screen_payload))
                continue
            
            # ─── Handle kiosk button press (direct navigation, no LLM) ───
            if msg_type == "kiosk_button_press":
                action = payload.get("action", "")
                params = payload.get("parameters", {})
                logger.info(f"Kiosk button pressed: {action}, params={params}")
                
                # Build a synthetic LLM action and execute it
                synthetic_action = {
                    "type": "kiosk_command",
                    "command": action,
                    "target_screen": "",
                    "parameters": params
                }
                result = session.execute_actions([synthetic_action])
                
                if result.get("screen_updated") and result.get("new_screen"):
                    screen_payload = {
                        "type": "kiosk_screen_update",
                        "screen": result["new_screen"]
                    }
                    await websocket.send_text(json.dumps(screen_payload))
                
                if result.get("errors"):
                    for err in result["errors"]:
                        logger.warning(f"Button action error: {err}")
                        error_payload = {
                            "type": "agent_response",
                            "reasoning": f"Button action error: {err}",
                            "actions": [{"type": "speech_output", "text": err, "language": "en"}],
                            "latency_ms": 0
                        }
                        await websocket.send_text(json.dumps(error_payload))
                continue
            
            # ─── Handle voice input — the main pipeline ───
            if msg_type == "user_audio_text":
                user_text = payload.get("text", "").strip()
                if not user_text:
                    continue
                
                start_time = time.time()
                
                # 1. Process through ASR handler
                processed = ASRHandler.process_transcript(user_text)
                
                # 2. Apply temporal decay to user state
                decay_user_state(session.user_state)
                
                # 3. Record interaction timing
                session.user_state.record_interaction(
                    response_time_ms=payload.get("response_time_ms", 2000)
                )
                
                # 4. Assemble Context Bundle
                context_bundle = ContextBundleAssembler.assemble(
                    user_transcript=processed["content"],
                    user_state=session.user_state,
                    kiosk_state=session.get_kiosk_state(),
                    conversation_history=session.conversation_history
                )
                
                # 5. Call the LLM
                llm_response = await call_llm(context_bundle)
                
                # 6. Execute actions through the kiosk state machine
                execution_result = session.execute_actions(llm_response.get("actions", []))
                
                # 7. Record in conversation history
                session.add_turn(user_text, llm_response)
                
                elapsed_ms = int((time.time() - start_time) * 1000)
                logger.info(f"Pipeline complete in {elapsed_ms}ms")
                
                # 8. Send LLM response + actions to the frontend
                response_payload = {
                    "type": "agent_response",
                    "reasoning": llm_response.get("reasoning", ""),
                    "actions": llm_response.get("actions", []),
                    "latency_ms": elapsed_ms
                }
                await websocket.send_text(json.dumps(response_payload))

                # 9. If kiosk screen changed, send screen update
                if execution_result.get("screen_updated") and execution_result.get("new_screen"):
                    screen_payload = {
                        "type": "kiosk_screen_update",
                        "screen": execution_result["new_screen"]
                    }
                    await websocket.send_text(json.dumps(screen_payload))

                # 10. Send any execution errors
                if execution_result.get("errors"):
                    for err in execution_result["errors"]:
                        logger.warning(f"Execution error: {err}")
            
            else:
                logger.warning(f"Unknown message type: {msg_type}")
            
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected — session {session_id}")
        session_mgr.remove(session_id)
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)


if __name__ == "__main__":
    logger.info("Starting UIAA Backend Server...")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=settings.DEBUG_MODE)
