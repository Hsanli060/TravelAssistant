"""验证：多入边 fan-in 时，下游节点是否等齐所有上游才执行（而不是有一个完成就跑）。

方法：三个上游节点用不同 sleep 时长（0.1s / 1s / 3s），
每个节点完成时打印时间戳；下游节点记录它启动时"已看到哪些上游的结果"。
如果 planner 启动时三个结果都齐了 → join 屏障成立。
如果 planner 只看到先完成的那几个 → 存在提前执行。
"""
import operator
import asyncio
import time
from typing import TypedDict, Annotated

from langgraph.graph import StateGraph, START, END


class State(TypedDict):
    weather: str
    hotel: str
    attraction: str
    events: Annotated[list, operator.add]   # reducer 合并三个并行分支的写入


def ts():
    return f"{time.strftime('%H:%M:%S')}.{int(time.time()*1000)%1000:03d}"


def log(msg):
    print(f"[{ts()}] {msg}", flush=True)


# --- 三个上游节点：故意不同耗时 ---
async def weather_agent(state):
    await asyncio.sleep(0.1)   # 最快：0.1 秒完成
    log("weather_agent 完成 (sleep 0.1s)")
    return {"weather": "W", "events": ["weather_done"]}

async def hotel_agent(state):
    await asyncio.sleep(1)     # 中等：1 秒完成
    log("hotel_agent 完成 (sleep 1s)")
    return {"hotel": "H", "events": ["hotel_done"]}

async def attraction_agent(state):
    await asyncio.sleep(3)     # 最慢：3 秒完成
    log("attraction_agent 完成 (sleep 3s)")
    return {"attraction": "A", "events": ["attraction_done"]}

# --- 下游节点：记录启动时看到了什么 ---
async def planner_agent(state):
    got = {
        "weather": state.get("weather"),
        "hotel": state.get("hotel"),
        "attraction": state.get("attraction"),
    }
    log(f"planner_agent 启动，读到的 state: {got}")
    assert all(got.values()), f"❌ 提前执行！缺上游数据: {got}"
    log("[OK] planner 拿到了全部三份数据 -> join 屏障成立")
    return {"events": ["planner_done"]}


workflow = StateGraph(State)
workflow.add_node("weather_agent", weather_agent)
workflow.add_node("hotel_agent", hotel_agent)
workflow.add_node("attraction_agent", attraction_agent)
workflow.add_node("planner_agent", planner_agent)

# 与项目完全相同的写法：START fan-out + 三条入边 fan-in
workflow.add_edge(START, "weather_agent")
workflow.add_edge(START, "hotel_agent")
workflow.add_edge(START, "attraction_agent")
workflow.add_edge("weather_agent", "planner_agent")
workflow.add_edge("hotel_agent", "planner_agent")
workflow.add_edge("attraction_agent", "planner_agent")
workflow.add_edge("planner_agent", END)

app = workflow.compile()

print("=" * 60)
print("实验：三上游 0.1s / 1s / 3s 不同耗时，观察 planner 启动时机")
print("=" * 60)
t0 = time.time()
asyncio.run(app.ainvoke({"events": []}))
print(f"总耗时: {time.time()-t0:.2f}s（并行应约 3s，串行会是 4.1s）")
