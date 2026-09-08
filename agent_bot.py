import os
from dotenv import load_dotenv

from anthropic import Anthropic

load_dotenv()
client = Anthropic()


# ---------- 1) Define tools ----------
tools = [
    {
        "name": "search_hotels",
        "description":"Query hotels in a city within a specified budget per night, returning hotel name, area, and price per night (in GBP).",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "city name, e.g., 'London'"},
                "max_price_per_night": {"type": "number", "description": "maximum budget per night (in GBP)"},
            },
            "required": ["city"],
        },
    },
    {
        "name": "search_restaurants",
        "description": "Query restaurants in a city within a specified area, returning restaurant name, area, cuisine, and average price (in GBP).",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "city name, e.g., 'London'"},
                "area": {"type": "string", "description": "area name, e.g., 'Camden', optional"},
            },
            "required": ["city"],
        },
    },

    {
        "name": "submit_plan",
        "description": "Submit the final selected travel plan, including the chosen hotels, restaurants, and their respective prices, for budget verification.",
        "input_schema": {
            "type": "object",
            "properties": {
                "budget": {"type": "number", "description": "The user's total budget (in GBP), extracted from the user's request"},
                "hotels": {
                    "type": "array",
                    "description": "The list of selected hotels, supporting multi-segment stays (staying at different hotels for different numbers of nights)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "hotel name"},
                            "price_per_night": {"type": "number", "description": "price per night (in GBP)"},
                            "nights": {"type": "number", "description": "number of nights stayed at this hotel"},
                        },
                        "required": ["name", "price_per_night", "nights"],
                    },
                },
                "restaurants": {
                    "type": "array",
                    "description": "The list of selected restaurants",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "restaurant name"},
                            "avg_price": {"type": "number", "description": "average price per person (in GBP)"},
                        },
                        "required": ["name", "avg_price"],
                    },
                },
            },
            "required": ["hotels", "restaurants", "budget"],
        },
},
]

# ---------- 2) Tool implementations (mock data) ----------
# name -> function mapping, used to dispatch tool calls in the loop
def search_hotels(city, max_price_per_night=None):
    hotels = [
        {"name": "Bloomsbury Inn", "area": "Bloomsbury", "price_per_night": 120},
        {"name": "Camden Lock Hotel", "area": "Camden", "price_per_night": 95},
        {"name": "Southbank Budget Stay", "area": "Southbank", "price_per_night": 75},
        {"name": "Mayfair Grand", "area": "Mayfair", "price_per_night": 280},
    ]
    if max_price_per_night is not None:
        hotels = [h for h in hotels if h["price_per_night"] <= max_price_per_night]
    return hotels

def search_restaurants(city, area=None):
    restaurants = [
        {"name": "Camden Noodle Bar", "area": "Camden", "cuisine": "Asian", "avg_price": 15},
        {"name": "Southbank Fish & Chips", "area": "Southbank", "cuisine": "British", "avg_price": 18},
        {"name": "Bloomsbury Bistro", "area": "Bloomsbury", "cuisine": "French", "avg_price": 30},
        {"name": "Camden Curry House", "area": "Camden", "cuisine": "Indian", "avg_price": 20},
    ]
    if area is not None:
        restaurants = [r for r in restaurants if r["area"].lower() == area.lower()]
    return restaurants

def evaluate_plan(plan, budget):
    """Pure calculation: sum up the total cost of the plan and compare it with the budget. Return (whether it passes, feedback message)."""
    # Total accommodation cost: iterate through each hotel, multiply price_per_night by nights, and accumulate
    hotel_cost = sum(h["price_per_night"] * h["nights"] for h in plan["hotels"])
    # Total food cost: iterate through each restaurant and accumulate avg_price
    food_cost = sum(r["avg_price"] for r in plan["restaurants"])
    total = hotel_cost + food_cost

    if total <= budget:
        return True, f"Total plan cost £{total}, within the budget £{budget}, passed."
    else:
        over = total - budget
        return False, f"Total plan cost £{total}, exceeds the budget £{budget} by £{over}. Please choose cheaper hotels or reduce the number of restaurants."

def review_plan(plan_text):
    """Independent LLM reviewer that assesses plan quality (subjective reasonableness),
    kept separate from the main agent. Returns (passed, review_comments)."""
    review_response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        #temperature=0,
        # system=(
        #     # "You are a critical travel plan reviewer. Assess whether the plan is "
        #     # "well-balanced and reasonable — consider location mix (are the hotel and "
        #     # "restaurants sensibly located?), spending balance, and overall experience. "
        #     # "If the plan is good, reply with exactly 'APPROVED'. "
        #     # "Otherwise, list the specific issues concisely so they can be fixed."

        # ),
        system=(
            "You are a strict travel plan reviewer. Check the plan against these criteria:\n"
            "1. LOCATION: FAIL if any restaurant is more than 3 miles from the hotel AND the plan "
            "does not mention transport time/cost. Otherwise PASS.\n"
            "2. BUDGET REALISM: FAIL if the budget breakdown lists only hotel and food prices "
            "without transport or service charges. Otherwise PASS.\n\n"
            "For EACH criterion, state PASS or FAIL with a one-line reason. "
            "Then end with a final line in the exact format: "
            "'VERDICT: APPROVED' (if all pass) or 'VERDICT: NEEDS_REVISION' (otherwise)."
        ),


        messages=[{"role": "user", "content": f"Review this travel plan:\n\n{plan_text}"}],
    )
    review_text = review_response.content[0].text
    passed = "VERDICT: APPROVED" in review_text
    #passed = "APPROVED" in review_text     # simple signal-word check
    return passed, review_text

# A mapping: name -> actual function, used to dispatch tool calls in the loop
TOOL_FUNCTIONS = {
    "search_hotels": search_hotels,
    "search_restaurants": search_restaurants,
}

# ---------- 3) User request ----------
messages = [
    {"role": "user", "content": "I want to visit London for 3 days, help me plan hotels and restaurants, with a total budget of 500 GBP. Please submit the plan after selection, ensuring it stays within budget."}
    #{"role": "user", "content": "I want to visit London for 3 days, help me plan hotels and restaurants."}
]

# ---------- 4) Agent loop ---------
turn = 0
max_turns = 8
last_plan = None
review_attempts = 0
max_reviews = 2        # Limit the number of review cycles to avoid infinite loops
budget_validated = False
force_submit = False

while turn < max_turns:
    turn +=1
    if force_submit:
        tool_choice_param = {"type": "tool", "name": "submit_plan"}
    else:
        tool_choice_param = {"type": "auto"}
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        system=(
            "You are a travel planning assistant. Please use search_hotels and search_restaurants to gather information,"
            "and after selecting a plan, you must call submit_plan to submit it for budget validation."
            "If the validation feedback indicates exceeding the budget, please adjust the plan (choose cheaper hotels or reduce the number of restaurants) and resubmit until it passes."
            "After passing validation, organize the final plan into a clear English response for the user."
            "If the user does not specify a budget, please ask for it before planning."
            #"Be strict: unless the plan is truly excellent, you must list at least one concrete issue and NOT reply APPROVED."

        ),

        tools=tools,
        tool_choice=tool_choice_param,
        messages=messages,
    )
    print("stop_reason:", response.stop_reason)

   # Model no longer needs tools -> print final answer and break
    if response.stop_reason != "tool_use":
        if not budget_validated:
            force_submit = True
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": "You must call submit_plan to validate the budget before presenting the plan."})
            continue  # Go to next turn to force submit_plan

        plan_text = ""
        for block in response.content:
            if block.type == "text":
                plan_text += block.text + "\n"
        

        passed, review_text = review_plan(plan_text)
        last_plan = plan_text 
        if passed:
            print("\nfinal answer:\n", plan_text)
            break
        else:
            review_attempts += 1
            if review_attempts >= max_reviews:
                # If the review limit is reached, show the current plan and exit
                print("\nfinal answer (review limit reached, showing current plan):\n", plan_text)
                break

            print("\n  → Reviewer flagged issues, revising...\n", review_text)
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": f"A reviewer raised these issues, please revise the plan:\n{review_text}"})
            budget_validated = False
            
            continue


    # Model wants to call tools -> append its turn to conversation history

    # Execute all tool calls from this turn and collect results
    messages.append({"role": "assistant", "content": response.content}) 
    tool_results = []

    for block in response.content:
        if block.type == "tool_use":
            if block.name == "submit_plan":
                force_submit = False  # Reset force_submit after successful evaluation   
                print("  → submit_plan was called! Starting budget validation...")   
                plan = block.input
                budget = plan.get("budget")   #use .get() so a missing key returns None instead of raising KeyError
                if budget is None:
                    content = "Missing budget information, unable to validate. Please confirm the total budget with the user."
                else:
                    print(f"  → Model extracted budget: £{budget}")
                    passed, feedback = evaluate_plan(plan, budget)
                    print(f"  → Validation result: {feedback}")
                    content = feedback
                    if passed:
                        budget_validated = True
                                   

            else:
                # This is a "data lookup" type tool → execute function as before
                try:
                    func = TOOL_FUNCTIONS[block.name]
                    result = func(**block.input)
                    content = str(result)
                except Exception as e:
                    content = f"Tool call error: {e}"
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": content,
            })

    # Feed tool results back into the conversation for the next turn
    messages.append({"role": "user", "content": tool_results})
    
    print(f"\n=== Entering turn {turn} ===\n")

else:
    if last_plan is not None:
        print("\nfinal answer (max turns reached, showing best plan so far):\n", last_plan)
    else:
        print("⚠️ Reached maximum turn limit without a valid plan. Please simplify your request.")

