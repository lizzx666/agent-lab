import os
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()
client = Anthropic()

# ---------- 1) 定义两个工具 ----------
tools = [
    {
        "name": "search_hotels",
        "description": "查询某个城市、每晚不超过指定预算的酒店，返回酒店名、区域、每晚价格(英镑)。",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市名，如 'London'"},
                "max_price_per_night": {"type": "number", "description": "每晚最高预算(英镑)"},
            },
            "required": ["city"],
        },
    },
    {
        "name": "search_restaurants",
        "description": "查询某个城市、某个区域的餐馆，返回餐馆名、区域、菜系、人均价格(英镑)。",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市名，如 'London'"},
                "area": {"type": "string", "description": "区域名，如 'Camden'，可选"},
            },
            "required": ["city"],
        },
    },

    {
        "name": "submit_plan",
        "description": "提交最终选定的旅行方案，包含选中的酒店、餐馆及各自价格，用于校验是否超预算。",
        "input_schema": {
            "type": "object",
            "properties": {
                "budget": {"type": "number", "description": "用户的总预算(英镑)，从用户需求中提取"},
                "hotels": {
                    "type": "array",
                    "description": "选定的酒店列表，支持多段住宿（不同酒店住不同晚数）",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "酒店名称"},
                            "price_per_night": {"type": "number", "description": "该酒店每晚价格(英镑)"},
                            "nights": {"type": "number", "description": "在这家酒店住的晚数"},
                        },
                        "required": ["name", "price_per_night", "nights"],
                    },
                },
                "restaurants": {
                    "type": "array",
                    "description": "选定的餐馆列表",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "餐馆名称"},
                            "avg_price": {"type": "number", "description": "该餐馆人均价格(英镑)"},
                        },
                        "required": ["name", "avg_price"],
                    },
                },
            },
            "required": ["hotels", "restaurants", "budget"],
        },
},
]

# ---------- 2) 两个工具的真实实现（假数据）----------
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
    """纯计算：把方案总价加出来，和预算比。返回 (是否通过, 反馈信息)。"""
    # 住宿总价：遍历每家酒店，各自 price_per_night × nights，累加
    hotel_cost = sum(h["price_per_night"] * h["nights"] for h in plan["hotels"])
    # 餐饮总价：遍历每家餐馆，把 avg_price 累加
    food_cost = sum(r["avg_price"] for r in plan["restaurants"])
    total = hotel_cost + food_cost

    if total <= budget:
        return True, f"方案总价 £{total}，在预算 £{budget} 内，通过。"
    else:
        over = total - budget
        return False, f"方案总价 £{total}，超出预算 £{budget} 共 £{over}，请改用更便宜的酒店或减少餐馆。"

# 一个映射：名字 -> 真实函数，循环里用它来分派
TOOL_FUNCTIONS = {
    "search_hotels": search_hotels,
    "search_restaurants": search_restaurants,
}

# ---------- 3) 用户请求 ----------
messages = [
    {"role": "user", "content": "我想去伦敦玩3天,帮我规划酒店和餐馆,总预算500英镑。请在选定方案后提交,确保不超预算。"}
    #{"role": "user", "content": "我想去伦敦玩3天,帮我规划酒店和餐馆。"}
]

# ---------- 4) Agent Loop：核心变化在这里 ----------
turn = 0
max_turns = 5


while turn < max_turns:

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        system=(
            "你是一个旅行规划助手。请先用 search_hotels 和 search_restaurants 搜集信息,"
            "选定方案后,必须调用 submit_plan 提交,由系统校验是否超预算。"
            "如果校验反馈超预算,请调整方案(换更便宜的酒店或减少餐馆)后重新提交,直到通过为止。"
            "校验通过后,再把最终方案整理成清晰的中文回复给用户。"
            "如果用户没有明确预算,请先询问预算后再规划。"
        ),
        tools=tools,
        messages=messages,
    )
    print("stop_reason:", response.stop_reason)

    # 模型不再需要工具了 → 打印最终回答，跳出循环
    if response.stop_reason != "tool_use":
        for block in response.content:
            if block.type == "text":
                print("\n最终回答：\n", block.text)
        break

    # 模型要调工具 → 把它的这轮回复存进对话历史
    messages.append({"role": "assistant", "content": response.content})

    # 执行它这一轮请求的所有工具调用，收集结果
    tool_results = []

    for block in response.content:
        if block.type == "tool_use":
            if block.name == "submit_plan":
                print("  → submit_plan 被调用了！开始校验预算...")   # 加这行
                plan = block.input
                budget = plan.get("budget")   # 用 .get，缺了返回 None，不会 KeyError
                if budget is None:
                    content = "缺少预算信息，无法校验。请先向用户确认总预算。"
                else:
                    print(f"  → 模型提取的预算: £{budget}")
                    passed, feedback = evaluate_plan(plan, budget)
                    print(f"  → 校验结果: {feedback}")                    # 加这行
                    content = feedback

            else:
                # 这是"查数据"类工具 → 照旧执行函数
                try:
                    func = TOOL_FUNCTIONS[block.name]
                    result = func(**block.input)
                    content = str(result)
                except Exception as e:
                    content = f"工具调用出错: {e}"
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": content,
            })

    # 把工具结果喂回对话，进入下一轮循环
    messages.append({"role": "user", "content": tool_results})
    turn += 1
    print(f"\n=== 进入第 {turn} 轮对话 ===\n")

else:
    print("⚠️ 已达到最大轮数上限，任务可能未完成，请简化需求后重试。")
    