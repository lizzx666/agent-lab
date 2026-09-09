import os
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()
client = Anthropic()

models = client.models.list()
print("Available models on your account:\n")
for m in models.data:
    print(f"{m.id:<30} {m.display_name}")