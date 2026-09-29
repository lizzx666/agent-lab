from dotenv import load_dotenv
load_dotenv()

from pydantic import BaseModel, Field
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.prebuilt import ToolNode


# ---------- 1) Tools: plain functions + type hints + docstrings ----------
# Function name -> tool name; docstring -> description; type hints -> input_schema

def search_hotels(city: str, max_price_per_night: float | None = None) -> list:
    """Query hotels in a city, optionally under a maximum price per night.

    Args:
        city: city name, e.g. 'London'
        max_price_per_night: maximum price per night in GBP (optional)

    Returns a list of hotels with name, area, and price_per_night (GBP).
    """
    hotels = [
        {"name": "Bloomsbury Inn", "area": "Bloomsbury", "price_per_night": 120},
        {"name": "Camden Lock Hotel", "area": "Camden", "price_per_night": 95},
        {"name": "Southbank Budget Stay", "area": "Southbank", "price_per_night": 75},
        {"name": "Mayfair Grand", "area": "Mayfair", "price_per_night": 280},
    ]
    if max_price_per_night is not None:
        hotels = [h for h in hotels if h["price_per_night"] <= max_price_per_night]
    return hotels


def search_restaurants(city: str, area: str | None = None) -> list:  
    """Query restaurants in a city, optionally in a specific area.

    Args:
        city: city name, e.g. 'London'
        area: specific area within the city (optional)

    Returns a list of restaurants with name, area, cuisine, and average price (in GBP).
    """
    restaurants = [
        {"name": "The Gourmet Kitchen", "area": "Bloomsbury", "cuisine": "French", "avg_price": 50},
        {"name": "Camden Delight", "area": "Camden", "cuisine": "Italian", "avg_price": 40},
        {"name": "Southbank Eats", "area": "Southbank", "cuisine": "British", "avg_price": 30},
        {"name": "Mayfair Fine Dine", "area": "Mayfair", "cuisine": "Japanese", "avg_price": 120},
    ]
    if area is not None:
        restaurants = [r for r in restaurants if r["area"].lower() == area.lower()]
    return restaurants

data_tools = [search_hotels, search_restaurants]


# ---------- 2) SubmitPlan schema + evaluator ----------


class HotelStay(BaseModel):
    name: str = Field(description="hotel name")              
    price_per_night: float = Field(description="price per night in GBP") 
    nights: int = Field(description="number of nights at this hotel")            

class RestaurantPick(BaseModel):
    name: str = Field(description="restaurant name")              
    avg_price: float = Field(description="average price per person in GBP")       

class SubmitPlan(BaseModel):
    """Submit the final selected travel plan for budget verification."""
    budget: float = Field(description="user's total budget in GBP, extracted from the request")          
    hotels: list[HotelStay] = Field(description="list of selected hotels with stay details")            
    restaurants: list[RestaurantPick] = Field(description="list of selected restaurants with average price")
    transport_cost: float = Field(default=0, description="estimated total local transport cost in GBP")
    service_charge: float = Field(default=0, description="estimated total service charges in GBP")



def evaluate_plan(plan: dict, budget: float):
    """Sum the plan cost and compare with the budget. Return (passed, feedback)."""

    hotel_cost = sum(h["price_per_night"] * h["nights"] for h in plan.get("hotels", []))
    food_cost = sum(r["avg_price"] for r in plan.get("restaurants", []))
    total_cost = hotel_cost + food_cost + plan.get("transport_cost", 0) + plan.get("service_charge", 0)
    if total_cost <= budget:
        return True, f"Plan is within budget. Total cost: £{total_cost}"
    else:
        return False, f"Plan exceeds budget by £{total_cost - budget}. Please choose cheaper hotels or reduce the number of restaurants."



# ---------- 3) State ----------
MAX_REVIEWS = 2   # the reviewer may send the plan back at most (MAX_REVIEWS - 1) times
MAX_FORCE = 2     # how many times we may force the model to call SubmitPlan

class TravelState(MessagesState):
    review_attempts: int
    review_passed: bool
    budget_validated: bool   # NEW: True only if the latest submitted plan passed evaluate_plan
    force_submit: bool       # NEW: when True, the next assistant call must use SubmitPlan
    force_attempts: int      # NEW: how many times we have forced so far (prevents an endless loop)


# ---------- 4) Helper: extract plain text from a message ----------
# AI message content can be a str OR a list of blocks (text blocks + tool_use blocks),
# as you saw in the printed output. This helper handles both.

def get_text(message) -> str:
    """Return the plain text of a message."""
    if isinstance(message.content, str):
        return message.content
    return "".join(
        block.get("text", "") for block in message.content if isinstance(block, dict)
    )

# ---------- 5) Reviewer: independent LLM, NO tools bound ----------
reviewer_llm = ChatAnthropic(model="claude-sonnet-4-6")

REVIEWER_PROMPT = (
    "You are a strict travel plan reviewer. Check the plan against these criteria:\n"
    "1. LOCATION: FAIL if any restaurant is more than 3 miles from the hotel AND the plan "
    "does not mention transport time/cost. Otherwise PASS.\n"
    "2. BUDGET REALISM: FAIL if the budget breakdown lists only hotel and food prices "
    "without transport or service charges. Otherwise PASS.\n\n"
    "For EACH criterion, state PASS or FAIL with a one-line reason. "
    "Then end with a final line in the exact format: "
    "'VERDICT: APPROVED' (if all pass) or 'VERDICT: NEEDS_REVISION' (otherwise)."
)

def review_plan(plan_text: str):
    """Independent LLM reviewer. Returns (passed, review_text)."""
    response = reviewer_llm.invoke([
        SystemMessage(content=REVIEWER_PROMPT),
        HumanMessage(content=plan_text)
    ])
    review_text = get_text(response)
    passed = "VERDICT: APPROVED" in review_text
    return passed, review_text



# ---------- 6) Main model and assistant node ----------

llm = ChatAnthropic(model="claude-sonnet-4-6")
all_tools = data_tools + [SubmitPlan]
llm_with_tools = llm.bind_tools(all_tools)
 

sys_msg = SystemMessage(content="You are a travel planning assistant. Please use search_hotels and search_restaurants to gather information,"
            "Include estimated transport_cost and service_charge in SubmitPlan (use 50 and 20 if unsure)."
            "After selecting a plan, you must call SubmitPlan to submit it for budget validation."
            "If the validation feedback indicates exceeding the budget, please adjust the plan (choose cheaper hotels or reduce the number of restaurants) and resubmit until it passes."
            "After passing validation, organize the final plan into a clear English response for the user."
            "If the user does not specify a budget, please ask for it before planning."
            
            )    



def assistant(state: TravelState):
    if state.get("force_submit", False):
        model = llm.bind_tools(all_tools, tool_choice="SubmitPlan")
    else:
        model = llm_with_tools
    return {"messages": [model.invoke([sys_msg] + state["messages"])]}


# ---------- 7) Evaluator node ----------
def submit_plan_node(state: TravelState):
    last_message = state["messages"][-1]
    results = []
    all_passed = True
    for call in last_message.tool_calls:
        if call["name"] == "SubmitPlan":
            plan = call["args"]
            budget = plan.get("budget")
            if budget is None:
                passed = False
                feedback = "Missing budget information, unable to validate. Please confirm the total budget with the user."
            else:
                passed, feedback = evaluate_plan(plan, budget)
            all_passed = all_passed and passed
            results.append(ToolMessage(content=feedback, tool_call_id=call["id"]))
    return {"messages": results, "budget_validated": all_passed, "force_submit": False}



# ---------- 8) Node that blocks an unvalidated answer ----------
def require_submit_node(state: TravelState):
    print("  -> answer blocked: no validated plan, forcing SubmitPlan next")   # visible log, so you can see it trigger
    return {
        "force_submit": True,
        "force_attempts": state.get("force_attempts", 0) + 1,
        "messages": [HumanMessage(content="Please call SubmitPlan to validate the budget first.")],   
    }




# ---------- 9) Reviewer node ----------
def reviewer_node(state: TravelState):
    plan_text = get_text(state["messages"][-1])        # the assistant's final answer
    attempts = state.get("review_attempts", 0) + 1     # .get: the key does not exist on the first pass
    passed, review_text = review_plan(plan_text)

    update = {
        "review_attempts": attempts,
        "review_passed": passed,
    }

    if not passed and attempts < MAX_REVIEWS:
        update["messages"] = [HumanMessage(
            content=f"A reviewer raised these issues, please revise the plan and resubmit it with SubmitPlan:\n{review_text}"
        )]
        update["budget_validated"] = False   # the plan is about to change, so the old validation no longer applies

    return update


def route_after_assistant(state: TravelState):
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        for call in last_message.tool_calls:
            if call["name"] == "SubmitPlan":
                return "submit_plan_node"
        return "tools"
    # no tool calls: the model wants to give a final answer
    if state.get("budget_validated", False):
        return "reviewer"
    if state.get("force_attempts", 0) >= MAX_FORCE:
        return END
    return "require_submit"


def route_after_review(state: TravelState):
    if state["review_passed"] or state["review_attempts"] >= MAX_REVIEWS:
        return END
    else:
        return "assistant"


# ---------- 11) Graph ----------
builder = StateGraph(TravelState)

# Nodes
builder.add_node("assistant", assistant)
builder.add_node("tools", ToolNode(data_tools))
builder.add_node("submit_plan_node", submit_plan_node)
builder.add_node("require_submit", require_submit_node)
builder.add_node("reviewer", reviewer_node)

# Edges
builder.add_edge(START, "assistant")
builder.add_conditional_edges("assistant", route_after_assistant,
                              ["tools", "submit_plan_node", "require_submit", "reviewer", END])
builder.add_edge("tools", "assistant")
builder.add_edge("submit_plan_node", "assistant")
builder.add_edge("require_submit", "assistant")
builder.add_conditional_edges("reviewer", route_after_review, ["assistant", END])

graph = builder.compile()



# ---------- 12) Run ----------
if __name__ == "__main__":
    initial_state = {
        "messages": [HumanMessage(content="I want to visit London for 3 days, total budget 500 GBP. Plan hotels and restaurants and submit the plan.")],
        "review_attempts": 0,
        "review_passed": False,
        "budget_validated": False,
        "force_submit": False,
        "force_attempts": 0,
    }
    result = graph.invoke(initial_state, config={"recursion_limit": 30})   # counterpart of max_turns in the hand-written version
    for m in result["messages"]:
        m.pretty_print()
    print("review_passed:", result["review_passed"])
    print("review_attempts:", result["review_attempts"])
    print("budget_validated:", result["budget_validated"])