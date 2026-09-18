# -*- coding: utf-8 -*-
"""4.4 验证实验：去掉 _call_lock 的并发 call_tool，观察原始报错形态。

两个假设对决：
  H1（我简历的原始说法）：并发写 stdio 管道 → 字节交错 → JSON 解析错误
  H2（面试官强候选）：高德服务端 QPS 限流 → 服务端报错返回

实验设计：
  A. 并发 3 个 call_tool（真实高德），收集每路的成功/失败与异常类型/报错文本
  B. 串行对照组：同样 3 个调用逐个跑
  每路调用带唯一关键词便于识别响应是否串台（搜索结果里检查是否混入他路关键词的结果）
"""
import asyncio
import sys, os, json, time
sys.path.insert(0, "backend")
from dotenv import load_dotenv
load_dotenv(os.path.join("backend", ".env"))

from app.config import get_settings
from app.services.mcp_service import MCPManager


async def one_call(mcp, tag: str, kw: str, city: str):
    """绕过 call_tool_text 的锁？——不行，锁在方法内。这里直接用 tools_map 原始调用，
    复刻 call_tool_text 的逻辑但【不加锁】，模拟无锁并发。"""
    t0 = time.perf_counter()
    try:
        tool = mcp.get_tool("maps_text_search")
        result = await asyncio.wait_for(tool.ainvoke({"keywords": kw, "city": city}), timeout=20.0)
        # 提取文本（复刻 call_tool_text 的解析）
        text = ""
        if isinstance(result, list):
            texts = []
            for item in result:
                if isinstance(item, dict) and "text" in item:
                    texts.append(item["text"])
                elif hasattr(item, "text"):
                    texts.append(str(item.text))
            text = "\n".join(texts)
        elif isinstance(result, dict) and "text" in result:
            text = str(result["text"])
        else:
            text = str(result)
        dt = time.perf_counter() - t0
        return {"tag": tag, "ok": True, "ms": int(dt * 1000), "text": text[:400]}
    except Exception as e:
        dt = time.perf_counter() - t0
        return {"tag": tag, "ok": False, "ms": int(dt * 1000),
                "etype": type(e).__name__, "emsg": str(e)[:300]}


async def main():
    mcp = MCPManager()
    await mcp.initialize()
    settings = get_settings()
    city = "北京"
    # 三个不同的关键词，结果可区分
    kws = {"A": "故宫", "B": "颐和园", "C": "天坛"}

    print("=" * 70)
    print("实验 A：无锁并发 3 路同一 stdio 会话")
    print("=" * 70)
    tasks = [one_call(mcp, tag, kw, city) for tag, kw in kws.items()]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for r in results:
        if isinstance(r, Exception):
            print(f"  [gather-exception] {type(r).__name__}: {str(r)[:200]}")
            continue
        if r["ok"]:
            # 检查响应是否串台：A 的结果里不应出现 B/C 的关键词
            cross = [k for k, v in kws.items() if k != r["tag"] and v in r["text"]]
            print(f"  [{r['tag']}] OK {r['ms']}ms  len={len(r['text'])}  串台检查: {'发现他路关键词!' + str(cross) if cross else '干净'}")
        else:
            print(f"  [{r['tag']}] FAIL {r['ms']}ms  {r['etype']}: {r['emsg'][:200]}")

    await asyncio.sleep(2)

    print()
    print("=" * 70)
    print("实验 B：串行对照组（同三个关键词逐个跑）")
    print("=" * 70)
    for tag, kw in kws.items():
        r = await one_call(mcp, tag, kw, city)
        if r["ok"]:
            print(f"  [{r['tag']}] OK {r['ms']}ms  len={len(r['text'])}")
        else:
            print(f"  [{r['tag']}] FAIL {r['ms']}ms  {r['etype']}: {r['emsg'][:200]}")
        await asyncio.sleep(0.5)

    await mcp.close()


if __name__ == "__main__":
    asyncio.run(main())
