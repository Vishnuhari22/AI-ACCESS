import asyncio
import os
from dotenv import load_dotenv

# We need to import the Agent from browser_use
try:
    from browser_use import Agent
    from langchain_google_genai import ChatGoogleGenerativeAI
except ImportError:
    print("Please install required packages:")
    print("pip install browser-use playwright langchain-google-genai python-dotenv")
    print("playwright install")
    exit(1)

# Load environment variables (e.g., GEMINI_API_KEY)
load_dotenv()

# Check for API key
if not os.getenv("GEMINI_API_KEY"):
    print("WARNING: GEMINI_API_KEY environment variable not found.")
    print("Please add it to your .env file in the backend directory.")
    print("Format: GEMINI_API_KEY=your_actual_key_here")
    exit(1)

# 1. Initialize the LLM (The 'brain' of the agent)
llm = ChatGoogleGenerativeAI(model="gemini-2.5-pro")

async def execute_booking_task():
    """
    This function tests Phase 1: Robust UI Automation using Browser Use.
    It targets a booking site to test dropdowns and text clearing.
    """
    
    # We define a complex goal that requires clearing text and handling dropdowns
    goal = (
        "Go to https://www.makemytrip.com. "
        "Close any promotional popups or login modals that appear on the screen. "
        "Click on the 'From' city field, clear any existing text, type 'New Delhi', and select it from the dropdown list. "
        "Click on the 'To' city field, clear any existing text, type 'Mumbai', and select it from the dropdown list. "
        "Click the 'Search' button."
    )
    
    print(f"Initializing Web Agent with goal:\n'{goal}'\n")
    
    # 2. Initialize the Browser Use Agent
    agent = Agent(
        task=goal,
        llm=llm,
    )
    
    # 3. Run the agent
    print("Agent is starting. A browser window should open shortly...")
    result = await agent.run()
    
    print("\n--- Task Complete ---")
    print("Result from Agent:", result)

if __name__ == "__main__":
    print("=== Accessibility Overlay: UI Automation PoC ===")
    asyncio.run(execute_booking_task())
