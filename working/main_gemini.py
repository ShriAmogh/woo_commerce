import sys
import logging
from orchestrator_gemini import GeminiOrchestrator

# Configure logging (both file + console)
log_fmt = '%(asctime)s - %(levelname)s - %(message)s'
logging.basicConfig(
    level=logging.INFO,
    format=log_fmt,
    handlers=[
        logging.FileHandler('app_gemini.log'),
        logging.StreamHandler()          # prints to terminal
    ]
)

def main():
    print("--- WooCommerce Natural Language Assistant (Gemini) ---")
    print("Type 'exit' to quit.")
    print("-------------------------------------------------------------")

    # Initialize Orchestrator
    try:
        orch = GeminiOrchestrator()
    except Exception as e:
        print(f"Error initializing assistant: {e}")
        return

    while True:
        try:
            user_input = input("\nYou: ").strip()
            if user_input.lower() in ['exit', 'quit']:
                print("Goodbye!")
                break

            if not user_input:
                continue

            print("Thinking (Gemini LLM)...")
            response = orch.handle_query(user_input)
            print(f"\nAssistant: {response}")

        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"\nAn error occurred: {e}")

if __name__ == "__main__":
    main()
