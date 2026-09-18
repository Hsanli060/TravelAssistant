# =====================================================================
# MCP 客户端管理服务（基于 langchain-mcp-adapters，弹性治理与自愈架构）
# =====================================================================
#
# 架构演进与核心治理能力：
#
# 1) 有限状态机（FSM）分层治理：
#    彻底弃用不可靠的单布尔值，引入 UNINITIALIZED / CONNECTING / HEALTHY /
#    DEGRADED / RECONNECTING / DEAD 六级状态，状态实时感知。
#
# 2) 反向探活（Probe-on-Timeout）精准区分"慢"与"死"：
#    业务调用发生 15s 超时后，不盲目杀进程，立即向子进程下发 1.5s 轻量 Ping 协议帧。
#    - Ping 成功：确诊为高德云端上游慢，管道正常，不重启，SDK 静默吸收迟到包；
#    - Ping 失败：确诊为子进程假死/管道崩溃，触发自愈重建。
#
# 3) 基于纪元版本（Generation-based）的单飞行受控自愈：
#    独占重建锁配合 _generation 纪元版本阻断惊群重建，2s 宽限期优雅关闭并回收孤儿进程，
#    重新冷启动握手，并在自愈成功后提供 1 次透明重试（Transparent 1-Retry），实现秒级无感自愈。
#
# 4) 会话宿主任务（Session Runner Task）规避 AnyIO 跨 Task 退出限制：
#    由专属后台协程持有 async with 上下文，彻底杜绝跨协程退出 CancelScope 的异常与管道泄露。
#
# 5) Per-Server 物理隔离与多服务扩展：
#    每个 MCP Server（如 amap、remote_sse 等）拥有独立生命周期容器、独立锁、
#    独立工具表与故障域，互不阻塞，支持 stdio 与 sse 传输层。
# =====================================================================

import os
import sys
import time
import asyncio
from enum import Enum
from typing import Dict, List, Optional, Any, Union
from loguru import logger

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_core.tools import BaseTool
from ..config import get_settings

settings = get_settings()


class ServerState(str, Enum):
    """MCP 服务状态枚举"""
    UNINITIALIZED = "uninitialized"  # 未初始化
    CONNECTING = "connecting"        # 连接 / 启动中
    HEALTHY = "healthy"              # 健康可用
    DEGRADED = "degraded"            # 亚健康（曾发生慢超时，但探活 Ping 存活）
    RECONNECTING = "reconnecting"    # 正在自愈重建会话（单飞行独占执行）
    DEAD = "dead"                    # 熔断 / 彻底不可用


def parse_tool_result(result: Any) -> str:
    """统一将 MCP 工具返回的各类结构（list, dict, object, str）解析为可读纯文本。"""
    if isinstance(result, list):
        texts = []
        for item in result:
            if isinstance(item, dict) and "text" in item:
                texts.append(str(item["text"]))
            elif hasattr(item, "text"):
                texts.append(str(item.text))
            else:
                texts.append(str(item))
        return "\n".join(texts)
    elif isinstance(result, dict) and "text" in result:
        return str(result["text"])
    return str(result)


class MCPServerInstance:
    """单个 MCP 服务的独立治理容器（故障隔离、独立锁、探活与单飞行自愈）。"""

    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config
        self.state: ServerState = ServerState.UNINITIALIZED

        self.client: Optional[MultiServerMCPClient] = None
        self._session: Optional[object] = None

        # 会话后台宿主任务（规避 anyio 跨 Task 调用 __aexit__ 的限制）
        self._session_runner_task: Optional[asyncio.Task] = None
        self._close_trigger: Optional[asyncio.Event] = None

        # 纪元版本号（Generation）：每次自愈重建成功递增，用于精准防惊群
        self._generation: int = 0

        # Per-Server 调用互斥锁，控制本服务内部 stdio 读写与 QPS 配额
        self._call_lock = asyncio.Lock()

        # 生命周期操作锁（初始化、手动关闭）
        self._lifecycle_lock = asyncio.Lock()

        # 单飞行自愈锁：防止多个请求并发发现会话故障时重复拉起多个子进程（惊群）
        self._reconnect_lock = asyncio.Lock()
        self._reconnect_event = asyncio.Event()
        self._reconnect_event.set()  # 初始非阻塞

        # 本 Server 挂载的工具字典：工具名 -> BaseTool
        self.tools_map: Dict[str, BaseTool] = {}

        # 统计指标与健康监控
        self.consecutive_failures: int = 0      #连续失败次数
        self.consecutive_timeouts: int = 0      #连续超时次数
        self.slow_calls_count: int = 0          #慢调用次数
        self.reconnect_count: int = 0           #重连次数
        self.last_ping_ms: float = -1.0    #上一次ping时间毫秒
        self.last_error: Optional[str] = None   #上一次错误

    async def _start_session_runner(self) -> None:
        """在专用后台协程中运行 session 上下文，保证进入与退出在同一 Task 内执行。"""
        ready_event=asyncio.Event()
        err_holder=[]
        self._close_trigger=asyncio.Event()
        async def _runner():
            try:
                self.client = MultiServerMCPClient({self.name: self.config})
                async with self.client.session(self.name) as session:
                    self._session = session
                    ready_event.set()
                    # 挂起等待外部关闭信号
                    await self._close_trigger.wait()
            except Exception as e:
                err_holder.append(e)
                ready_event.set()
            finally:
                self._session=None
                self.client=None
        self._session_runner_task=asyncio.create_task(_runner())
        await ready_event.wait()

        if err_holder:
            raise err_holder[0]

    async def initialize(self) -> None:
        """启动并连接 MCP 服务，建立持久会话，加载工具并执行就绪握手。"""
        async with self._lifecycle_lock:
            if self.state == ServerState.HEALTHY and self.tools_map:
                return

            self.state = ServerState.CONNECTING
            logger.info(f"🔌 正在启动 MCP 服务: [{self.name}] (transport={self.config.get('transport', 'stdio')})...")

            await self._safe_close_session()

            try:
                # 启动后台会话宿主任务
                await self._start_session_runner()

                # 加载工具并绑定持久会话
                all_tools = await load_mcp_tools(self._session, server_name=self.name)
                self.tools_map = {tool.name: tool for tool in all_tools}

                # 初始 Ping 探活验证
                ping_ok = await self.ping(timeout=2.5)
                if not ping_ok:
                    raise RuntimeError(f"[{self.name}] 初始握手 Ping 探活失败")

                self.state = ServerState.HEALTHY
                self.consecutive_failures = 0
                self.last_error = None
                logger.info(f"✅ [{self.name}] 服务启动成功！挂载 {len(self.tools_map)} 个工具，Ping 延迟: {self.last_ping_ms}ms")

            except Exception as e:
                self.state = ServerState.DEAD
                self.last_error = str(e)
                await self._safe_close_session()
                logger.error(f"❌ [{self.name}] 启动失败: {e}")
                raise

    async def ping(self, timeout: float = 1.5) -> bool:
        """轻量级反向探活：用于区分'上游 API 慢'还是'本地子进程僵死'。

        优先使用 MCP 标准 ping 协议帧（session.send_ping），
        若不支持则回退到轻量反射协议（session.list_tools）。
        """
        if self._session is None:
            return False

        t0 = time.perf_counter()
        try:
            if hasattr(self._session, "send_ping"):
                await asyncio.wait_for(self._session.send_ping(), timeout=timeout)
            elif hasattr(self._session, "list_tools"):
                await asyncio.wait_for(self._session.list_tools(), timeout=timeout)
            else:
                return True

            self.last_ping_ms = round((time.perf_counter() - t0) * 1000, 2)
            return True
        except Exception as e:
            self.last_ping_ms = -1.0
            self.last_error = f"Ping probe failed: {e}"
            return False

    async def _safe_close_session(self) -> None:
        """安全关闭会话：通知 runner 退出并在其内部优雅执行 __aexit__，带 2s 超时防挂起。"""

        #是否有关闭事件，并且关闭事件没有触发
        if self._close_trigger is not None and not self._close_trigger.is_set():
            self._close_trigger.set()

        #后台是否有任务已经被创建了，并且该任务还在执行中
        if self._session_runner_task is not None and not self._session_runner_task.done():
            try:
                await asyncio.wait_for(self._session_runner_task, timeout=2.0)
            except Exception as e:
                logger.warning(f"⚠️ [{self.name}] 等待会话任务结束超时或异常: {e}，强制取消")
                self._session_runner_task.cancel()
                try:
                    await self._session_runner_task
                except (asyncio.CancelledError, Exception):
                    pass

        self._session_runner_task = None
        self._close_trigger = None
        self._session = None
        self.client = None

    async def reconnect(self, current_gen: Optional[int] = None) -> None:
        """基于纪元版本（Generation）的单飞行受控自愈：阻断并发惊群，安全重建会话并刷新工具绑定。"""
        async with self._reconnect_lock:
            # 纪元双重检查：若排队期间已有协程完成了更高 generation 的重建，直接复用
            if current_gen is not None and self._generation > current_gen and self.state == ServerState.HEALTHY:
                return

            self.state = ServerState.RECONNECTING
            self._reconnect_event.clear()
            self.reconnect_count += 1
            logger.warning(f"🔄 [{self.name}] 触发单飞行会话自愈 (第 {self.reconnect_count} 次重建)...")

            try:
                # 1. 强力安全清理旧会话
                await self._safe_close_session()

                # 2. 重新启动会话宿主
                await self._start_session_runner()

                # 3. 重新拉取工具对象并绑定新 session
                all_tools = await load_mcp_tools(self._session, server_name=self.name)
                self.tools_map = {tool.name: tool for tool in all_tools}

                # 4. 握手验真
                ping_ok = await self.ping(timeout=2.0)
                if not ping_ok:
                    raise RuntimeError(f"[{self.name}] 自愈重建后 Ping 验真未通过")

                self._generation += 1
                self.state = ServerState.HEALTHY
                self.consecutive_failures = 0
                self.consecutive_timeouts = 0
                self.last_error = None
                logger.info(f"✅ [{self.name}] 会话自愈成功 (gen={self._generation})！工具已重新绑定，就绪可用")

            except Exception as e:
                self.state = ServerState.DEAD
                self.last_error = f"Reconnection failed: {str(e)}"
                logger.error(f"❌ [{self.name}] 会话自愈失败: {e}")
                raise
            finally:
                # 广播唤醒所有等待自愈完成的在途请求
                self._reconnect_event.set()

    async def call_tool_text(
        self,
        tool_name: str,
        tool_input: dict,
        timeout: float = 15.0,
        allow_retry: bool = True
    ) -> str:
        """执行工具调用：含 15s 超时熔断、反向探活诊断、单飞行自愈与 1 次透明重试。"""
        max_attempts = 2 if allow_retry else 1

        for attempt in range(max_attempts):
            # 若正处于自愈阶段，挂起等待自愈完成（最长等待 10s）
            if self.state == ServerState.RECONNECTING:
                try:
                    await asyncio.wait_for(self._reconnect_event.wait(), timeout=10.0)
                except asyncio.TimeoutError:
                    raise RuntimeError(f"[{self.name}] 等待会话自愈超时，快速失败")

            # 若未初始化或处于死亡状态，先尝试拉起
            if self.state in (ServerState.UNINITIALIZED, ServerState.DEAD) or self._session is None:
                await self.initialize()

            # 记录本次发起调用时的纪元号
            call_gen = self._generation

            tool = self.tools_map.get(tool_name)
            if not tool:
                raise KeyError(
                    f"未找到 MCP 工具: '{tool_name}'。当前 [{self.name}] 可用工具: {list(self.tools_map.keys())}"
                )

            need_reconnect = False      #需要重新连接
            is_upstream_slow = False    #上游缓慢
            call_error_msg = None       #通话错误提示

            try:
                # 加 Per-Server 锁保护 stdio 管道并限制并发在途
                async with self._call_lock:
                    raw = await asyncio.wait_for(tool.ainvoke(tool_input), timeout=timeout)

                # 调用成功收尾
                self.consecutive_failures = 0
                self.consecutive_timeouts = 0
                if self.state == ServerState.DEGRADED:
                    self.state = ServerState.HEALTHY
                return parse_tool_result(raw)

            except asyncio.TimeoutError:
                self.consecutive_timeouts += 1
                self.slow_calls_count += 1

                # 核心机制：1.5s 反向探活确认"慢"还是"死"
                is_alive = await self.ping(timeout=1.5)
                if is_alive:
                    # 管道存活：确诊为高德云端上游慢，绝不盲目杀进程
                    self.state = ServerState.DEGRADED
                    is_upstream_slow = True
                    logger.warning(
                        f"⚠️ [{self.name}] 工具 '{tool_name}' 单次调用超时 ({timeout}s)，"
                        f"但反向 Ping 探活存活（{self.last_ping_ms}ms）——判定为上游响应慢，保留会话。"
                    )
                else:
                    # 探活失败：确诊为子进程假死 / 管道已崩
                    self.consecutive_failures += 1
                    need_reconnect = True
                    call_error_msg = f"Timeout ({timeout}s) with dead probe"
                    logger.error(
                        f"🚨 [{self.name}] 工具 '{tool_name}' 调用超时 ({timeout}s) 且反向探活失败——"
                        f"确诊为会话假死，触发自愈重建！"
                    )

            except Exception as e:
                # 捕获管道损坏、子进程意外退出等严重通信错误
                self.consecutive_failures += 1
                err_repr = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
                self.last_error = err_repr
                need_reconnect = True
                call_error_msg = err_repr
                logger.error(f"🚨 [{self.name}] 工具 '{tool_name}' 通信异常: {err_repr}——触发自愈重建！")

            # 分支 1：上游慢，不重建会话，直接抛出交由 Agent 既定降级链处理
            if is_upstream_slow:
                raise asyncio.TimeoutError(
                    f"Tool '{tool_name}' timed out after {timeout}s (upstream API slow, session intact)"
                )

            # 分支 2：确诊会话死亡，触发受控自愈
            if need_reconnect:
                await self.reconnect(current_gen=call_gen)
                # 若仍有重试预算，执行 1 次透明重试（Transparent 1-Retry）
                if attempt < max_attempts - 1:
                    logger.info(f"🔁 [{self.name}] 会话已成功自愈，正在透明重试工具 '{tool_name}' (1-Retry)...")
                    continue
                else:
                    raise RuntimeError(
                        f"Tool '{tool_name}' failed ({call_error_msg}) and retry exhausted"
                    )

        raise RuntimeError(f"Tool '{tool_name}' execution unexpected exit")

    async def close(self) -> None:
        """安全关闭该 Server，释放子进程。"""
        async with self._lifecycle_lock:
            await self._safe_close_session()
            self.tools_map.clear()
            self.state = ServerState.UNINITIALIZED
            logger.info(f"🔌 [{self.name}] MCP 服务连接已安全关闭。")

    def get_health(self) -> dict:
        """导出该 Server 当前实时健康报告快照。"""
        return {
            "name": self.name,
            "state": self.state.value,
            "transport": self.config.get("transport", "stdio"),
            "generation": self._generation,
            "tools_count": len(self.tools_map),
            "consecutive_failures": self.consecutive_failures,
            "consecutive_timeouts": self.consecutive_timeouts,
            "slow_calls_count": self.slow_calls_count,
            "reconnect_count": self.reconnect_count,
            "last_ping_ms": self.last_ping_ms,
            "last_error": self.last_error,
        }


class MCPManager:
    """管理系统对接的所有 MCP 服务（全局单例门面，多 Server 编排与弹性网关）。

    向下兼容所有现有 Agent 调用，内部统一路由至对应的 MCPServerInstance。
    """
    _instance: Optional["MCPManager"] = None

    def __init__(self):
        # 多 Server 注册容器：server_name -> MCPServerInstance
        self.servers: Dict[str, MCPServerInstance] = {}

        # 全局工具缓存表：tool_name -> BaseTool
        self.tools_map: Dict[str, BaseTool] = {}

        # 工具路由索引表：tool_name -> MCPServerInstance
        self._tool_to_server: Dict[str, MCPServerInstance] = {}

        # 全局初始化锁
        self._init_lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> "MCPManager":
        """获取全局唯一实例。"""
        if cls._instance is None:
            cls._instance = MCPManager()
        return cls._instance

    @property
    def _is_initialized(self) -> bool:
        """向下兼容历史布尔属性：若至少有一个 Server 处于 HEALTHY 则返回 True。"""
        return any(s.state == ServerState.HEALTHY for s in self.servers.values())

    @property
    def client(self):
        """向下兼容历史 client 属性：返回默认 amap server 的 client。"""
        amap_server = self.servers.get("amap")
        return amap_server.client if amap_server else None

    # ------------------------------------------------------------------
    # 构建 MCP Server 配置（支持多服务与不同传输协议扩展）
    # ------------------------------------------------------------------
    def _get_server_configs(self) -> dict:
        """获取系统配置的所有 MCP 服务配置字典。"""
        sub_env = os.environ.copy()
        sub_env.update({
            "AMAP_MAPS_API_KEY": settings.amap_api_key,
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        })

        configs = {
            "amap": {
                "command": "uvx",
                "args": ["amap-mcp-server"],
                "env": sub_env,
                "transport": "stdio",
            }
            # 未来若接入远程服务，声明即可无缝扩展：
            # "remote_service": {
            #     "transport": "sse",
            #     "url": "http://mcp.internal:8000/sse",
            # }
        }
        return configs

    # ------------------------------------------------------------------
    # 全局初始化
    # ------------------------------------------------------------------
    async def initialize(self):
        """启动并初始化所有注册的 MCP Server，建立全局工具路由表。"""
        async with self._init_lock:
            if self._is_initialized and self.tools_map:
                return

            if not settings.amap_api_key:
                raise ValueError("未配置 AMAP_API_KEY，无法初始化高德地图 MCP 服务")

            configs = self._get_server_configs()

            # 初始化或复用 ServerInstance
            for name, conf in configs.items():
                if name not in self.servers:
                    self.servers[name] = MCPServerInstance(name, conf)

            # 并行初始化各个 Server（故障隔离，互不阻塞）
            init_tasks = [s.initialize() for s in self.servers.values()]
            results = await asyncio.gather(*init_tasks, return_exceptions=True)

            for s, res in zip(self.servers.values(), results):
                if isinstance(res, Exception):
                    logger.error(f"❌ Server [{s.name}] 初始化失败: {res}")

            # 重新构建全局工具表与路由索引（提供别名与前缀双重兼容）
            self._rebuild_tools_index()

            logger.info(
                f"🌟 MCP 网关初始化完毕：已就绪 {len(self.servers)} 个服务，"
                f"聚合挂载 {len(self.tools_map)} 个可用工具"
            )

    def _rebuild_tools_index(self):
        """汇总各 Server 工具，生成全局工具表与路由映射。"""
        self.tools_map.clear()
        self._tool_to_server.clear()

        for s_name, server in self.servers.items():
            for t_name, tool in server.tools_map.items():
                # 1. 注册原生短名（如 maps_text_search）
                self.tools_map[t_name] = tool
                self._tool_to_server[t_name] = server

                # 2. 注册带服务名前缀全名（如 amap__maps_text_search），避免未来命名冲突
                prefixed_name = f"{s_name}__{t_name}"
                self.tools_map[prefixed_name] = tool
                self._tool_to_server[prefixed_name] = server

    # ------------------------------------------------------------------
    # 对外工具查询接口（100% 兼容原接口）
    # ------------------------------------------------------------------
    def get_tool(self, tool_name: str) -> BaseTool:
        """根据工具名称获取工具对象。"""
        if tool_name not in self.tools_map:
            raise KeyError(
                f"未找到 MCP 工具: '{tool_name}'。当前可用工具: {list(self.tools_map.keys())}"
            )
        return self.tools_map[tool_name]

    def get_all_tools(self) -> List[BaseTool]:
        """获取所有可用工具列表（去重后）。"""
        # 只返回原生短名工具，避免重复
        seen = set()
        tools = []
        for name, tool in self.tools_map.items():
            if "__" not in name and name not in seen:
                seen.add(name)
                tools.append(tool)
        return tools

    def get_server(self, server_name: str) -> Optional[MCPServerInstance]:
        """获取指定 Server 治理容器实例。"""
        return self.servers.get(server_name)

    # ------------------------------------------------------------------
    # 统一调用入口（100% 兼容原签名，自动路由至对应 Server 容器）
    # ------------------------------------------------------------------
    async def call_tool_text(self, tool_name: str, tool_input: dict, timeout: float = 15.0) -> str:
        """统一调用 MCP 工具，自动路由至对应 Server 容器并返回纯文本。"""
        if not self._is_initialized:
            await self.initialize()

        server = self._tool_to_server.get(tool_name)
        if not server:
            # 尝试刷新一次工具路由索引
            self._rebuild_tools_index()
            server = self._tool_to_server.get(tool_name)

        if not server:
            raise KeyError(f"未找到工具 '{tool_name}' 所属的 MCP 服务实例")

        # 还原为 server 内部识别的 tool_name（若为 prefixed，剥离前缀）
        actual_tool_name = tool_name.split("__", 1)[1] if "__" in tool_name else tool_name

        # 委托给具体 Server 容器执行（享受该 Server 的独立锁、超时判定与自愈重试）
        result_text = await server.call_tool_text(actual_tool_name, tool_input, timeout=timeout)

        # 若发生过自愈，同步更新全局工具映射
        if len(server.tools_map) != len(self.tools_map):
            self._rebuild_tools_index()

        return result_text

    # ------------------------------------------------------------------
    # 健康检查与全景监控报告
    # ------------------------------------------------------------------
    def get_health_status(self) -> dict:
        """获取 MCP 网关及所有子服务的全景健康状态报告。"""
        server_reports = {name: s.get_health() for name, s in self.servers.items()}
        states = [s.state for s in self.servers.values()]

        if not states:
            overall_status = ServerState.UNINITIALIZED.value
        elif all(st == ServerState.HEALTHY for st in states):
            overall_status = ServerState.HEALTHY.value
        elif any(st == ServerState.DEAD for st in states):
            overall_status = ServerState.DEAD.value
        elif any(st in (ServerState.DEGRADED, ServerState.RECONNECTING) for st in states):
            overall_status = ServerState.DEGRADED.value
        else:
            overall_status = ServerState.CONNECTING.value

        return {
            "status": overall_status,
            "total_servers": len(self.servers),
            "total_tools": len(self.get_all_tools()),
            "servers": server_reports,
        }

    # ------------------------------------------------------------------
    # 收尾关闭
    # ------------------------------------------------------------------
    async def close(self):
        """关闭所有 MCP Server 连接，释放所有持久会话子进程。"""
        async with self._init_lock:
            close_tasks = [s.close() for s in self.servers.values()]
            if close_tasks:
                await asyncio.gather(*close_tasks, return_exceptions=True)
            self.servers.clear()
            self.tools_map.clear()
            self._tool_to_server.clear()
            logger.info("🔌 MCP 网关已全部安全关闭。")


def get_mcp_manager() -> MCPManager:
    """获取 MCP 管理器全局单例。"""
    return MCPManager.get_instance()
