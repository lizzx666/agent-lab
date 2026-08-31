import os
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()
client = Anthropic()

# 1) 定义工具：告诉模型有这么个能力，以及怎么调用它
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
    }
]

# 2) 工具的真实实现（先用假数据）
def search_hotels(city, max_price_per_night=None):
    fake = [
        {"name": "Bloomsbury Inn", "area": "Bloomsbury", "price_per_night": 120},
        {"name": "Camden Lock Hotel", "area": "Camden", "price_per_night": 95},
        {"name": "Southbank Budget Stay", "area": "Southbank", "price_per_night": 75},
        {"name": "Mayfair Grand", "area": "Mayfair", "price_per_night": 280},
    ]
    if max_price_per_night is not None:
        fake = [h for h in fake if h["price_per_night"] <= max_price_per_night]
    return fake

# 3) 用户请求
messages = [
    #{"role": "user", "content": "推荐伦敦的住宿，每晚预算不超过 100 英镑"}
    #{"role": "user", "content": "随便推荐几家伦敦酒店"}
    {"role": "user", "content": "请问你能帮我做什么？"}
]

# 4) 第一次调用：模型看到有工具，可能会决定调用它
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1000,
    tools=tools,
    messages=messages,
)
print("stop_reason:", response.stop_reason)

# 5) 如果模型要求调工具，就执行它，再把结果喂回去
if response.stop_reason == "tool_use":
    messages.append({"role": "assistant", "content": response.content})

    tool_results = []
    for block in response.content:
        if block.type == "tool_use":
            print("模型调用了:", block.name, block.input)
            if block.name == "search_hotels":
                result = search_hotels(**block.input)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": str(result),
            })

    messages.append({"role": "user", "content": tool_results})

    # 6) 第二次调用：模型拿到工具结果，给出最终回答
    final = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        tools=tools,
        messages=messages,
    )
    for block in final.content:
        if block.type == "text":
            print(block.text)
else:
    for block in response.content:
        if block.type == "text":
            print(block.text)