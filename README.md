# Travel Agent Bot

Travel Agent Bot is a tool-using travel planning agent built from scratch with the Anthropic API. It demonstrates the agent loop, structured output, and an evaluator–optimizer budget check. See `agent_bot.py` for the full implementation.

## Features

- Multiple tool calls, each for a specific task (hotels, restaurants, plan submission)
- A multi-turn agent loop that iterates toward a valid plan
- Error handling and graceful handling of missing user input
- A turn limit to prevent infinite loops
- A deterministic budget check to ensure the plan stays within budget
- Structured output (via tool schema) for reliable parsing

## Design Decisions

**Why display output as a table?**

After trying several display formats — and based on my own experience with several planning agents — I found a table to be clear and easy to read. The final response also highlights the budget remaining after hotel and meal costs, so the user can see how much is left for other expenses.

**Why a code-based evaluator instead of an LLM?**

Budget checking is deterministic arithmetic: sum the costs and compare against the limit. Code does this reliably and repeatably, whereas an LLM can miscalculate and would add unnecessary uncertainty. Keeping this step in plain code also keeps the overall agent flow simpler. An LLM is not needed here, so a fixed evaluator is enough.

**Why set a turn limit in the agent loop?**

Even with a clean design, the agent is not guaranteed to behave correctly every time (for example, it might keep calling tools without finishing). A turn limit prevents infinite loops and stops the user from waiting indefinitely for a result. When the limit is reached, the agent prints a notice instead of failing silently, which also makes it easier to see where the process stalled.

**How are missing inputs handled?**

User requests can be vague, e.g. "Can you recommend some restaurants and hotels in London?" To produce a tailored plan, the agent needs the user's rough budget. If the budget is missing, the agent asks for it in the next turn instead of guessing. This is backed up in code: the budget is read with `.get()`, so a missing value is handled safely rather than crashing.

## How It Works

1. The user makes a request, e.g. "I want to stay in London for 3 days with a total budget of £500 — can you recommend some hotels and restaurants?"
2. After parsing the user's city and budget, the agent calls `search_hotels` to find hotels that meet the requirements, returning each hotel's name, area, and price per night.
3. The same process applies to restaurants: `search_restaurants` returns each restaurant's name, area, cuisine, and average price.
4. The agent then calls `submit_plan` to check whether the total cost of the selected hotels and restaurants is within the user's budget. If it is, the final plan (hotel and restaurant details plus a cost breakdown) is returned. If it exceeds the budget, the evaluator feeds back the overage and the agent starts another round of selection.

## Setup and Run

1. Add your Anthropic API key to a `.env` file:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```
2. Run the agent:
   ```
   uv run python agent_bot.py
   ```

## Next Steps

- **Real data:** Hotel and restaurant prices are currently mock data. The plan is to replace this with a real database or API to support real use cases.
- **Force the budget check with `tool_choice`:** During testing, the agent sometimes skipped the `submit_plan` step and claimed a plan was within budget when it had not actually been verified — which would be a bad experience in production. Applying `tool_choice` will force the agent to call `submit_plan`, guaranteeing the check actually runs.
