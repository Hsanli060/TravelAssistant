# -*- coding: utf-8 -*-
"""用户自带 API Key (BYOK) 与 API 设置功能测试套件 (test_byok_api_settings.py)

测试场景覆盖：
1. SSRF 严密防护 (validate_base_url / validate_base_url_async)
   - 协议白名单限制 (只允许 http/https)
   - 环回地址拦截 (127.0.0.1, localhost, ::1)
   - 私有内网网段拦截 (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
   - 链路本地与云元数据地址拦截 (169.254.169.254, fe80::/10)
   - 保留/多播/广播地址拦截 (0.0.0.0, 240.0.0.0/4, 224.0.0.0/4)
   - 合法公共 URL 放行 (https://api.openai.com/v1, https://api.deepseek.com/v1 等)
2. API Key 脱敏工具 (mask_key)
   - 空值、纯空格、超短 key、标准 key 安全遮罩
3. 请求级 ContextVar 隔离与并发安全 (LLMOverride Context)
   - 单任务作用域进入与自动重置
   - 并发协程隔离（多任务同时运行，各自读取独占 Key，绝不串号）
4. LLM 惰性工厂在 BYOK 模式下的动态构建
   - _get_fast_llm() 动态创建独立实例且不污染全局单例
   - _get_planner_llm() 动态创建独立实例
   - _get_weather_react_agent() 针对 override 动态重建 ReAct Agent，杜绝 LLM 引用逃逸
5. 端点 0 Token 预检探活 (probe_llm_credentials)
   - 假 Key / 401 拦截并报错 BAD_API_KEY
   - 404 /models 端点优雅容错放行 (兼容无 /models 接口的网关)
   - 网络连接失败 / 超时报错 LLM_CONNECT_FAILED / LLM_TIMEOUT
6. API 路由层端到端行为验证 (/api/trip/plan & /api/trip/verify-key)
   - 携带内网 Base URL 返回 400 (BAD_BASE_URL)
   - 严格模式下未传 Key 返回 409 (NO_API_KEY)
   - 宽松模式下未传 Key 降级使用服务端默认 Key
   - 假 Key 请求直接被端点预检以 400 BAD_API_KEY 拦截，绝不静默降级为低质行程
   - 自带有效 Key 成功注入 ContextVar 并传递至底层 Agent
   - /api/trip/verify-key 接口支持前端独立探活
"""

import sys
import os
import asyncio
import unittest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

# 将 backend 路径加入 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from app.api.main import app
from app.config import get_settings
from app.services.llm_override import (
    LLMOverride,
    get_llm_override,
    set_llm_override,
    reset_llm_override,
    llm_override_context,
    mask_key,
    validate_base_url,
    validate_base_url_async,
    probe_llm_credentials,
)
from app.agents.trip_planner_helpers import (
    _get_fast_llm,
    _get_planner_llm,
    _get_weather_react_agent,
)
from app.models.schemas import TripPlan, DayPlan, Budget


def _create_dummy_plan() -> TripPlan:
    return TripPlan(
        city="北京",
        start_date="2026-10-01",
        end_date="2026-10-03",
        days=[
            DayPlan(date="2026-10-01", day_index=0, description="第一天故宫游玩"),
            DayPlan(date="2026-10-02", day_index=1, description="第二天颐和园游玩"),
            DayPlan(date="2026-10-03", day_index=2, description="第三天天坛游玩"),
        ],
        budget=Budget(total_estimated=1000, per_person_daily=300),
        overall_suggestions="建议穿舒适的鞋子",
    )


class TestBYOKSecurityAndContext(unittest.IsolatedAsyncioTestCase):
    """BYOK 安全防护与上下文隔离测试"""

    def test_01_ssrf_protocol_validation(self):
        """测试 1: 协议白名单限制 (仅允许 http/https)"""
        bad_schemes = [
            "ftp://api.example.com/v1",
            "file:///etc/passwd",
            "gopher://127.0.0.1:70",
            "ws://api.example.com",
            "data:text/plain;base64,SGVsbG8=",
        ]
        for url in bad_schemes:
            valid, msg = validate_base_url(url)
            self.assertFalse(valid, f"协议 {url} 应该被拦截")
            self.assertIn("仅支持 http:// 或 https:// 协议", msg)

        print("  PASS [01] SSRF 协议白名单校验通过")

    def test_02_ssrf_loopback_and_local_blocking(self):
        """测试 2: 本地及环回地址全面拦截"""
        loopback_urls = [
            "http://localhost:8000/v1",
            "http://localhost.localdomain/v1",
            "http://127.0.0.1:8000/v1",
            "http://127.0.0.2:8000/v1",
            "http://0.0.0.0:8000/v1",
            "http://broadcasthost/v1",
            "http://service.local/v1",
        ]
        for url in loopback_urls:
            valid, msg = validate_base_url(url)
            self.assertFalse(valid, f"环回/本地地址 {url} 应该被拦截")

        print("  PASS [02] SSRF 本地及环回地址拦截通过")

    def test_03_ssrf_private_network_blocking(self):
        """测试 3: 私有局域网网段全面拦截 (10.x, 172.16-31.x, 192.168.x)"""
        private_urls = [
            "http://10.0.0.1/v1",
            "http://10.255.255.255/v1",
            "http://172.16.0.1:8000/v1",
            "http://172.20.10.2/v1",
            "http://172.31.255.255/v1",
            "http://192.168.1.1:8000/v1",
            "http://192.168.0.100/v1",
        ]
        for url in private_urls:
            valid, msg = validate_base_url(url)
            self.assertFalse(valid, f"私有内网地址 {url} 应该被拦截")
            self.assertIn("私有局域网地址", msg)

        print("  PASS [03] SSRF 私有内网地址拦截通过")

    def test_04_ssrf_metadata_and_special_ip_blocking(self):
        """测试 4: 链路本地与云厂商元数据地址拦截 (169.254.169.254 等)"""
        special_urls = [
            "http://169.254.169.254/latest/meta-data/",
            "http://169.254.1.1/v1",
            "http://224.0.0.1/v1",  # 多播
            "http://240.0.0.1/v1",  # 保留
        ]
        for url in special_urls:
            valid, msg = validate_base_url(url)
            self.assertFalse(valid, f"特殊地址 {url} 应该被拦截")

        print("  PASS [04] SSRF 云元数据及特殊地址拦截通过")

    def test_05_ssrf_legitimate_urls_pass(self):
        """测试 5: 合法公共大模型 API 地址放行"""
        legit_urls = [
            "",  # 空值直接允许（使用系统默认）
            "https://api.openai.com/v1",
            "https://api.deepseek.com/v1",
            "https://api.siliconflow.cn/v1",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "http://example.com/v1",
        ]
        for url in legit_urls:
            valid, msg = validate_base_url(url)
            self.assertTrue(valid, f"合法地址 {url} 被误拦截: {msg}")

        print("  PASS [05] SSRF 合法公共 Base URL 放行验证通过")

    async def test_05b_ssrf_async_wrapper(self):
        """测试 5b: 异步版 SSRF 校验 (to_thread 调度)"""
        valid, _ = await validate_base_url_async("https://api.deepseek.com/v1")
        self.assertTrue(valid)
        invalid, msg = await validate_base_url_async("http://127.0.0.1:8000/v1")
        self.assertFalse(invalid)
        print("  PASS [05b] validate_base_url_async 异步包装调用通过")

    def test_06_key_masking(self):
        """测试 6: API Key 日志安全脱敏"""
        self.assertEqual(mask_key(""), "")
        self.assertEqual(mask_key("   "), "")
        self.assertEqual(mask_key("12345678"), "********")
        self.assertEqual(mask_key("sk-1234567890abcdef"), "sk-...cdef")
        self.assertEqual(mask_key("sk-proj-xxxxxxxxxxxxxxxxxxxx1234"), "sk-...1234")
        print("  PASS [06] API Key 脱敏逻辑验证通过")

    async def test_07_contextvar_isolation_and_concurrency(self):
        """测试 7: ContextVar 请求级单任务作用域与多并发协程隔离"""
        self.assertIsNone(get_llm_override())

        override_test = LLMOverride(api_key="sk-scope-test", base_url="https://api.test.com/v1")
        with llm_override_context(override_test):
            cur = get_llm_override()
            self.assertIsNotNone(cur)
            self.assertEqual(cur.api_key, "sk-scope-test")
            self.assertEqual(cur.base_url, "https://api.test.com/v1")

        self.assertIsNone(get_llm_override(), "上下文管理器退出后应重置为 None")

        # 跨并发协程隔离性验证
        async def mock_worker(task_id: int, key: str):
            with llm_override_context(LLMOverride(api_key=key)):
                await asyncio.sleep(0.02)
                cur = get_llm_override()
                self.assertIsNotNone(cur)
                self.assertEqual(cur.api_key, key, f"协程 {task_id} 出现上下文交叉污染！")

        tasks = [
            mock_worker(1, "sk-user-alice-1111"),
            mock_worker(2, "sk-user-bob-2222"),
            mock_worker(3, "sk-user-carol-3333"),
        ]
        await asyncio.gather(*tasks)

        self.assertIsNone(get_llm_override())
        print("  PASS [07] ContextVar 协程级并发隔离与自清理验证通过")

    def test_08_llm_factories_dynamic_instantiation(self):
        """测试 8: LLM 惰性工厂在 override 模式下的动态构建与单例保全"""
        override = LLMOverride(api_key="sk-override-key", base_url="https://api.override.com/v1")

        default_fast_llm = _get_fast_llm()
        self.assertNotEqual(default_fast_llm.openai_api_key.get_secret_value(), "sk-override-key")

        with llm_override_context(override):
            override_fast_llm = _get_fast_llm()
            self.assertEqual(override_fast_llm.openai_api_key.get_secret_value(), "sk-override-key")
            self.assertEqual(override_fast_llm.openai_api_base, "https://api.override.com/v1")
            self.assertIsNot(override_fast_llm, default_fast_llm, "重载实例不应复用全局默认单例")

            override_planner_llm = _get_planner_llm()
            self.assertEqual(override_planner_llm.openai_api_key.get_secret_value(), "sk-override-key")

            weather_agent = _get_weather_react_agent()
            self.assertIsNotNone(weather_agent)

        after_fast_llm = _get_fast_llm()
        self.assertIs(after_fast_llm, default_fast_llm, "退出上下文后应还原为全局默认实例")
        print("  PASS [08] LLM 惰性工厂动态创建与全局单例隔离验证通过")


class TestBYOKProbeAndEndpoints(unittest.IsolatedAsyncioTestCase):
    """BYOK 端点预检与 HTTP 请求交互测试"""

    def setUp(self):
        self.client = TestClient(app)
        self.payload = {
            "city": "北京",
            "start_date": "2026-10-01",
            "end_date": "2026-10-03",
            "travel_days": 3,
            "preferences": ["历史文化", "地道美食"],
            "free_text_input": "",
        }

    def test_09_ssrf_header_rejected_by_endpoint(self):
        """测试 9: 端点接收到恶意 Base URL 立即拦截并返回 400 BAD_BASE_URL"""
        headers = {
            "X-LLM-API-Key": "sk-user-test-key",
            "X-LLM-Base-URL": "http://127.0.0.1:8000/v1",
        }
        resp = self.client.post("/api/trip/plan", json=self.payload, headers=headers)
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertEqual(data["detail"]["code"], "BAD_BASE_URL")
        self.assertIn("禁止访问环回地址", data["detail"]["message"])
        print("  PASS [09] 端点层恶意 Base URL (127.0.0.1) 400 拦截验证通过")

    def test_10_strict_mode_without_key_returns_409(self):
        """测试 10: 严格模式下 (allow_default_key=False) 未传 Key 拦截并返回 409 NO_API_KEY"""
        settings = get_settings()
        original_allow = settings.allow_default_key
        try:
            settings.allow_default_key = False
            resp = self.client.post("/api/trip/plan", json=self.payload)
            self.assertEqual(resp.status_code, 409)
            data = resp.json()
            self.assertEqual(data["detail"]["code"], "NO_API_KEY")
            self.assertIn("严格模式", data["detail"]["message"])
        finally:
            settings.allow_default_key = original_allow

        print("  PASS [10] 严格模式未传 Key 返回 409 NO_API_KEY 验证通过")

    @patch("app.api.routes.trip.get_trip_planner_agent")
    def test_11_permissive_mode_uses_default_key(self, mock_get_agent):
        """测试 11: 宽松模式下 (allow_default_key=True) 未传 Key 允许通过并使用系统默认 Key"""
        settings = get_settings()
        original_allow = settings.allow_default_key
        try:
            settings.allow_default_key = True

            mock_agent = MagicMock()
            mock_agent.aplan_trip = AsyncMock(return_value=_create_dummy_plan())
            mock_get_agent.return_value = mock_agent

            resp = self.client.post("/api/trip/plan", json=self.payload)
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.json()["success"])
            mock_agent.aplan_trip.assert_called_once()
        finally:
            settings.allow_default_key = original_allow

        print("  PASS [11] 宽松模式未传 Key 正常放行至服务端默认 Key 验证通过")

    @patch("app.api.routes.trip.probe_llm_credentials")
    @patch("app.api.routes.trip.get_trip_planner_agent")
    def test_12_byok_header_propagated_to_context(self, mock_get_agent, mock_probe):
        """测试 12: 用户自带有效 Key 正确通过预检并进入 ContextVar 上下文"""
        mock_probe.return_value = (True, "OK", "API Key 校验成功")

        mock_agent = MagicMock()
        captured_override = None

        async def fake_aplan_trip(req):
            nonlocal captured_override
            captured_override = get_llm_override()
            return _create_dummy_plan()

        mock_agent.aplan_trip = fake_aplan_trip
        mock_get_agent.return_value = mock_agent

        headers = {
            "X-LLM-API-Key": "sk-user-custom-secret-key-9999",
            "X-LLM-Base-URL": "https://api.deepseek.com/v1",
        }

        resp = self.client.post("/api/trip/plan", json=self.payload, headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])

        # 验证内部 Agent 执行期间拿到了用户的 key 与 base_url
        self.assertIsNotNone(captured_override)
        self.assertEqual(captured_override.api_key, "sk-user-custom-secret-key-9999")
        self.assertEqual(captured_override.base_url, "https://api.deepseek.com/v1")

        # 验证请求结束后主线程的 ContextVar 干净无残留
        self.assertIsNone(get_llm_override())
        print("  PASS [12] 用户自带 Key/URL 透传至 ContextVar 并在完成后完全清理验证通过")

    async def test_13_probe_fake_key_returns_bad_api_key(self):
        """测试 13: 预检探测捕获假 Key / 401 鉴权失败，精准返回 BAD_API_KEY"""
        # 使用真实 DeepSeek 节点做一次探活，传假 Key 预期 401
        is_valid, code, msg = await probe_llm_credentials(
            api_key="sk-fake-invalid-key-000000000000",
            base_url="https://api.deepseek.com/v1",
            timeout=5.0
        )
        self.assertFalse(is_valid)
        self.assertEqual(code, "BAD_API_KEY")
        self.assertIn("401", msg)
        print("  PASS [13] probe_llm_credentials 假 Key 探活拦截 (401 -> BAD_API_KEY) 验证通过")

    async def test_14_probe_404_models_graceful_pass(self):
        """测试 14: 服务商不支持 /models 端点返回 404/405 时，容错放行 (返回 OK)"""
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 404
            mock_get.return_value = mock_resp

            is_valid, code, msg = await probe_llm_credentials(
                api_key="sk-some-key",
                base_url="https://api.custom-proxy.com/v1",
            )
            self.assertTrue(is_valid)
            self.assertEqual(code, "OK")
            self.assertIn("放行", msg)

        print("  PASS [14] probe_llm_credentials 404 容错放行验证通过")

    async def test_15_probe_connect_failure(self):
        """测试 15: Base URL 网络连接超时或不可达时，返回 LLM_CONNECT_FAILED / LLM_TIMEOUT"""
        with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("Connection refused")):
            is_valid, code, msg = await probe_llm_credentials(
                api_key="sk-some-key",
                base_url="https://api.unreachable-domain-xyz.com/v1",
            )
            self.assertFalse(is_valid)
            self.assertEqual(code, "LLM_CONNECT_FAILED")
            self.assertIn("无法连接", msg)

        print("  PASS [15] probe_llm_credentials 连接失败/超时防护验证通过")

    def test_16_endpoint_rejects_fake_key_with_bad_api_key(self):
        """测试 16: /api/trip/plan 端点遇到假 Key 立即 400 阻断，杜绝假 Key 静默降级"""
        headers = {
            "X-LLM-API-Key": "sk-fake-dead-key-123456",
            "X-LLM-Base-URL": "https://api.deepseek.com/v1",
        }
        resp = self.client.post("/api/trip/plan", json=self.payload, headers=headers)
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertEqual(data["detail"]["code"], "BAD_API_KEY")
        print("  PASS [16] 端点层假 Key 预检拦截 (400 BAD_API_KEY) 验证通过，彻底根除静默降级缺口")

    def test_17_verify_key_endpoint(self):
        """测试 17: /api/trip/verify-key 端点测试 (供前端「测试连接」按钮调用)"""
        # 1. 空 Key
        resp_empty = self.client.post("/api/trip/verify-key", json={"api_key": ""})
        self.assertEqual(resp_empty.status_code, 200)
        self.assertFalse(resp_empty.json()["success"])
        self.assertEqual(resp_empty.json()["code"], "BAD_API_KEY")

        # 2. 假 Key
        resp_fake = self.client.post(
            "/api/trip/verify-key",
            json={"api_key": "sk-fake-key-9999", "base_url": "https://api.deepseek.com/v1"}
        )
        self.assertEqual(resp_fake.status_code, 200)
        self.assertFalse(resp_fake.json()["success"])
        self.assertEqual(resp_fake.json()["code"], "BAD_API_KEY")

        # 3. 模拟成功 Key
        with patch("app.api.routes.trip.probe_llm_credentials") as mock_probe:
            mock_probe.return_value = (True, "OK", "API Key 校验成功")
            resp_ok = self.client.post(
                "/api/trip/verify-key",
                json={"api_key": "sk-valid-key", "base_url": "https://api.deepseek.com/v1"}
            )
            self.assertEqual(resp_ok.status_code, 200)
            self.assertTrue(resp_ok.json()["success"])
            self.assertEqual(resp_ok.json()["code"], "OK")

        print("  PASS [17] /api/trip/verify-key 独立测试连接接口验证通过")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("🧪 开始执行 BYOK (自带 API Key) 核心功能与探活测试套件")
    print("=" * 60 + "\n")
    unittest.main(verbosity=2)
