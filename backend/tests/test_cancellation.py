# -*- coding: utf-8 -*-
"""用户主动取消规划及断开连接中断机制测试套件 (test_cancellation.py)

测试场景：
1. 客户端通过 POST /api/trip/cancel 显式取消正在进行的规划任务：
   - 后端立即中断正在运行的 aplan_trip Task
   - 请求返回 HTTP 499 (Client Closed Request)
   - 杜绝后续 Agent 调度与 LLM 消耗
2. 取消不存在或已结束的任务，接口幂等优雅返回
3. 规划正常完成后，活跃任务注册表自动清理，无内存泄漏
"""

import sys
import os
import asyncio
import unittest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from app.api.main import app
from app.api.routes.trip import _active_plan_tasks
from app.models.schemas import TripPlan, Budget


class TestCancellationSuite(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.payload = {
            "city": "北京",
            "start_date": "2026-10-01",
            "end_date": "2026-10-03",
            "travel_days": 3,
            "transportation": "公共交通",
            "accommodation": "舒适型酒店",
            "preferences": ["历史文化", "特色美食"],
            "free_text_input": "测试取消机制"
        }
        _active_plan_tasks.clear()

    def tearDown(self):
        _active_plan_tasks.clear()

    def test_cancel_nonexistent_or_completed_task(self):
        """测试 1: 取消不存在或已完成的任务，接口幂等返回 200"""
        resp = self.client.post("/api/trip/cancel", json={"request_id": "nonexistent_task_999"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertIn("任务已完成或未找到", data["message"])

    def test_normal_completion_cleans_registry(self):
        """测试 2: 正常生成的规划任务完成后，活跃任务表自动清理"""
        mock_plan = TripPlan(
            city="北京",
            start_date="2026-10-01",
            end_date="2026-10-03",
            days=[],
            budget=Budget(total=1500),
            overall_suggestions="测试建议"
        )

        with patch("app.api.routes.trip.get_trip_planner_agent") as mock_get_agent, \
             patch("app.api.routes.trip.get_settings") as mock_settings:
            settings_mock = MagicMock()
            settings_mock.allow_default_key = True
            mock_settings.return_value = settings_mock

            mock_agent = MagicMock()
            mock_agent.aplan_trip = AsyncMock(return_value=mock_plan)
            mock_get_agent.return_value = mock_agent

            req_id = "test-normal-req-001"
            headers = {"X-Plan-Request-Id": req_id}
            resp = self.client.post("/api/trip/plan", json=self.payload, headers=headers)

            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.json()["success"])
            # 确认任务注册表中无残留
            self.assertNotIn(req_id, _active_plan_tasks)

    def test_explicit_cancel_stops_task_and_saves_tokens(self):
        """测试 3: 前端发送取消指令后，后台立即中断异步任务并返回 499，停止消耗 Token"""
        async def run_async_test():
            cancelled_event = asyncio.Event()
            step_after_cancel_reached = False

            async def slow_mock_aplan_trip(req):
                try:
                    # 模拟第 1 步天气智能体运行
                    await asyncio.sleep(0.1)
                    # 模拟耗时等待（在此期间将收到取消信号）
                    await asyncio.sleep(2.0)
                    nonlocal step_after_cancel_reached
                    step_after_cancel_reached = True
                    return TripPlan(city="北京", travel_days=3, itinerary=[])
                except asyncio.CancelledError:
                    cancelled_event.set()
                    raise

            with patch("app.api.routes.trip.get_trip_planner_agent") as mock_get_agent, \
                 patch("app.api.routes.trip.get_settings") as mock_settings:
                settings_mock = MagicMock()
                settings_mock.allow_default_key = True
                mock_settings.return_value = settings_mock

                mock_agent = MagicMock()
                mock_agent.aplan_trip = slow_mock_aplan_trip
                mock_get_agent.return_value = mock_agent

                req_id = "test-cancel-req-777"
                headers = {"X-Plan-Request-Id": req_id}

                # 使用 async httpx 客户端并发发起规划与取消
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
                    # 启动规划请求
                    plan_coro = ac.post("/api/trip/plan", json=self.payload, headers=headers)
                    plan_task = asyncio.create_task(plan_coro)

                    # 等待任务注册进 _active_plan_tasks
                    for _ in range(20):
                        if req_id in _active_plan_tasks:
                            break
                        await asyncio.sleep(0.05)
                    self.assertIn(req_id, _active_plan_tasks)

                    # 发送取消请求
                    cancel_resp = await ac.post("/api/trip/cancel", json={"request_id": req_id})
                    self.assertEqual(cancel_resp.status_code, 200)
                    self.assertTrue(cancel_resp.json()["success"])

                    # 等待规划请求返回并验证其被阻断为 499
                    plan_resp = await plan_task
                    self.assertEqual(plan_resp.status_code, 499)

                    # 验证 CancelledError 被触发，且后续步骤绝对未执行
                    self.assertTrue(cancelled_event.is_set())
                    self.assertFalse(step_after_cancel_reached)

                    # 验证活跃任务表已被清理
                    self.assertNotIn(req_id, _active_plan_tasks)

        asyncio.run(run_async_test())


if __name__ == "__main__":
    unittest.main()
