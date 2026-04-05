import asyncio
from lira.core.agent import Agent

async def main():
    agent = Agent()
    print("Agent ready")
    async for event in agent.run_streaming("Add a transaction of 5$ for tissues for the checking account"):
        print(event.model_dump_json())

if __name__ == "__main__":
    asyncio.run(main())
