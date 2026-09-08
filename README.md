# Travel Agent Bot

Travel Agent Bot is a tool-using travel planning agent built from scratch with the Anthropic API. It demonstrates the agent loop, structured output, and a two-layer evaluator (a deterministic budget check plus an LLM reviewer), with mechanism-level guardrails rather than prompt-only requests. See `agent_bot.py` for the full implementation.

## Features

- Multiple tool calls, each for a specific task (hotels, restaurants, plan submission)
- A multi-turn agent loop that iterates toward a valid plan
- Error handling and graceful handling of missing user input
- A turn limit and a review limit to prevent infinite loops
- **Deterministic budget check** — plan cost is summed and compared against the budget in plain code (not the LLM), so the check is exact and repeatable
- **LLM reviewer (reflection)** — an independent LLM reviews the plan against explicit, objective criteria (restaurant-to-hotel distance, budget realism) and sends it back for revision if it fails
- **`tool_choice` enforcement** — the model is *forced* to call `submit_plan` before a plan can reach the user, so the budget check can never be silently skipped
- Structured output (via tool schema) for reliable parsing
- Graceful fallback — if limits are reached, the best plan so far is returned instead of failing silently

## Design Decisions

**Why display output as a table?**

After trying several display formats — and based on my own experience with several planning agents — I found a table to be clear and easy to read. The final response also highlights the budget remaining after hotel and meal costs, so the user can see how much is left for other expenses.

**Why a code-based evaluator instead of an LLM?**

Budget checking is deterministic arithmetic: sum the costs and compare against the limit. Code does this reliably and repeatably, whereas an LLM can miscalculate and would add unnecessary uncertainty. Keeping this step in plain code also keeps the overall agent flow simpler. The subjective quality check — is the plan reasonable? — is a separate concern and is left to the LLM reviewer, since that genuinely needs judgment.

**Why enforce `submit_plan` with `tool_choice` instead of just asking in the prompt?**

Early on, the model would sometimes skip `submit_plan` entirely — it would do the arithmetic itself and declare the plan "within budget," bypassing the real check. A system prompt saying "you must call submit_plan" is only a request, and the model can ignore it. (In testing it ignored instructions in both directions — skipping the tool when told to call it, and calling it when told not to.) So the plan is tracked with a `budget_validated` flag; if the model tries to finish without a validated plan, `tool_choice` forces it to call `submit_plan` on the next turn. The guarantee comes from the mechanism, not from the prompt.

**Why an LLM reviewer with objective criteria?**

The reviewer catches quality problems the budget check can't — e.g. a hotel in one area with restaurants 5 miles away, or a budget that ignores transport. Early versions used vague criteria ("is the plan reasonable?") and the verdict was unstable — the same plan passed some runs and failed others. Rewriting the criteria as objective, checkable rules (fail if a restaurant is >3 miles from the hotel with no transport noted; fail if the budget omits transport or service charges) made the reviewer far more consistent.

**Why set turn and review limits?**

The agent is not guaranteed to converge — a strict reviewer could keep flagging issues forever. A turn limit prevents infinite loops, and a separate review limit stops the review cycle from stalling the whole run. When a limit is reached, the best plan so far is shown rather than failing silently.

**How are missing inputs handled?**

User requests can be vague, e.g. "Can you recommend some restaurants and hotels in London?" To produce a tailored plan, the agent needs the user's rough budget. If the budget is missing, the agent asks for it in the next turn instead of guessing. This is backed up in code: the budget is read with `.get()`, so a missing value is handled safely rather than crashing.

## How It Works

1. The user makes a request, e.g. "I want to stay in London for 3 days with a total budget of £500 — can you recommend some hotels and restaurants?"
2. The agent calls `search_hotels` and `search_restaurants` to gather options (mock data for now), returning each place's name, area, price, etc.
3. The agent calls `submit_plan` with its chosen hotels, restaurants, and the budget it extracted from the request. The code runs a deterministic budget check.
4. If over budget, the overage is fed back and the agent re-plans. If within budget, the plan goes to the LLM reviewer for a quality check against objective criteria.
5. If the reviewer flags issues, they are fed back and the agent revises. If it passes (or the review limit is hit), the final plan is returned.
6. Throughout, `tool_choice` ensures the model cannot present a plan to the user without it having passed the budget check.

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
- **Real distance data:** The location check currently relies on the model's own distance estimates. Wiring in a maps API would turn this into a true external-feedback check based on measured distances.
- **Observability:** Print-based logging works for now; a tracing tool (e.g. LangSmith or Langfuse) would give better visibility into each step's tool calls, cost, and latency.
