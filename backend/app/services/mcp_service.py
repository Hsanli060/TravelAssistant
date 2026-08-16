# =====================================================================
# MCP 客户端管理服务（基于 langchain-mcp-adapters，持久会话模式）
# =====================================================================
#
# 先搞懂 4 个核心概念，再看代码就轻松了：
#
# 1) MCP (Model Context Protocol) —— "模型上下文协议"
#    一套标准协议，规定"AI 应用"怎么去调用"外部工具"（搜地图、查天气、查数据库…）。
#    类比 USB：外设（工具）按统一接口插上电脑（AI 应用），不用关心内部实现。
#
# 2) MCP Client / MCP Server —— 协议两端
#      - Server：提供工具的一方，是一个独立进程。这里就是 uvx 拉起的
#        amap-mcp-server，它内部真正去请求高德地图 REST API。
#      - Client：调用工具的一方。本文件里的 MultiServerMCPClient 就是 Client。
#    两端通过"标准输入输出(stdin/stdout)"传 JSON 文本互相通信（叫 stdio 传输）。
#
# 3) 会话 (Session)
#    Client 和 Server 建立一次连接叫"一个会话"。本文件用"持久会话"：
#    整个应用只连一次、一直用，避免每次调用工具都重新启动子进程（很慢）。
#
# 4) 工具 (Tool) / LangChain 工具
#    高德 Server 暴露 16 个"能力"，如 maps_text_search（搜景点）。
#    langchain 把每个能力包装成一个"工具对象"，供大模型/AI 应用调用。
#
# 本文件就是：MCP Client 的管理器 —— 负责建立/维护连接、加载工具、统一调用。
# =====================================================================

import os
import asyncio
from typing import Dict, List, Optional
# MultiServerMCPClient：langchain 官方封装好的"MCP 客户端"类。
from langchain_mcp_adapters.client import MultiServerMCPClient

# load_mcp_tools：把 MCP Server 暴露的工具，转换成"LangChain 工具对象"。
# 传入 session 时，转换出来的工具会绑定在这个持久会话上，复用它通信。
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_core.tools import BaseTool
from ..config import get_settings
settings = get_settings()


class MCPManager:
    """管理系统对接的所有 MCP 服务（单例模式，持有持久会话）。

    关键设计：
    - MCP 会话在整个应用生命周期内只建立一次并持有；
    - 所有工具调用都走同一个持久会话，避免"每次调用都重启 uvx 子进程"（实测约 1 秒/次）。
    """
    _instance: Optional["MCPManager"] = None

    def __init__(self):
        # ---------- 实例变量（属于"每个对象自己"，每次 new 都是全新的一份） ----------
        # client：MCP 客户端对象，没连接前是 None
        self.client: Optional[MultiServerMCPClient] = None
        self.tools_map: Dict[str, BaseTool] = {}

        # _session_cm：持久会话的"异步上下文管理器"（后面专门讲 __aenter__/__aexit__）
        self._session_cm: Optional[object] = None

        # _session：持久会话对象，真正用来和 Server 通信的东西
        self._session: Optional[object] = None

        # _is_initialized：是否已经初始化完成的标记，避免重复连接
        self._is_initialized: bool = False

        # _init_lock：异步锁。防止多个请求同时进来时，重复初始化同一套连接
        self._init_lock = asyncio.Lock()

        # _call_lock：调用互斥锁，防止 stdio 管道并发读写导致的数据竞争
        self._call_lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> "MCPManager":
        """获取全局唯一实例。
        """
        if cls._instance is None:
            cls._instance = MCPManager()
        return cls._instance

    # ------------------------------------------------------------------
    # 构建 MCP 客户端（只配置，不立即连接）
    # ------------------------------------------------------------------
    def _build_client(self) -> MultiServerMCPClient:
        """构造指向高德 MCP Server 的客户端（只是"写好配置"，还没真正连接）。
        -> MultiServerMCPClient 是返回值类型标注：表示这个方法返回一个该类型的对象。
        """
        # os.environ 是"当前程序的全部环境变量"的字典。
        # copy() 复制一份，避免污染原字典。
        sub_env = os.environ.copy()

        # 在副本上追加"子进程专用"的环境变量
        sub_env.update({
            "AMAP_MAPS_API_KEY": settings.amap_api_key,
            # 强制子进程的标准输入/输出用 UTF-8 编码，防止中文乱码
            "PYTHONIOENCODING": "utf-8",
            # 强制子进程的 Python 开启 UTF-8 模式
            "PYTHONUTF8": "1",
        })

        # 构造客户端。传入一个字典，告诉它"有一个叫 amap 的 MCP 服务，怎么启动它"
        return MultiServerMCPClient({
            "amap": {                    # 服务名，本类里统一用 "amap" 指代它
                "command": "uvx",        # 启动命令：uvx 是 Python 的工具运行器（类似 npx）
                "args": ["amap-mcp-server"],  # 参数：要运行的程序名（一个 PyPI 包）
                "env": sub_env,          # 启动子进程时带上的环境变量（含密钥）
                "transport": "stdio",    # 通信方式：stdio = 标准输入输出（默认方式）
            }
        })

    # ------------------------------------------------------------------
    # 初始化：连接 Server、建立持久会话、加载工具
    # ------------------------------------------------------------------
    async def initialize(self):
        """启动并连接高德 MCP 服务，建立持久会话并加载全部工具。
        失败时清理残留状态并向上抛出（raise），让调用方（lifespan / aplan_trip）感知，
        """
        # 其他协程会在 `async with` 这行"排队等待"，前一个退出后才进入。
        async with self._init_lock:
            # 已经初始化过了，并且工具表里有东西 → 直接返回，不重复连接
            if self._is_initialized and self.tools_map:
                return

            # 没配置高德密钥，直接抛异常（raise = 抛出），说明为什么不行
            if not settings.amap_api_key:
                raise ValueError("未配置 AMAP_API_KEY，无法初始化高德地图 MCP 服务")

            # 先清理可能残留的旧连接（比如上一次失败留下的半成品）
            await self._close_session()

            print("🔌 正在启动并连接高德地图 MCP 服务 (amap-mcp-server)...")

            try:
                self.client = self._build_client()

                # 2. 进入持久会话。
                # self.client.session("amap") 返回一个"异步上下文管理器"对象，
                # 它的 __aenter__() 负责真正去连接 Server。
                # 手动调用 __aenter__() 的效果 = 用 `async with` 进入，
                # 但手动调用可以把它"保存起来"，等 close() 时再手动 __aexit__() 退出。
                self._session_cm = self.client.session("amap")
                self._session = await self._session_cm.__aenter__()

                # 3. 用这个持久会话去加载工具。
                # 传给 load_mcp_tools 一个 session，得到的工具就会绑定在这个会话上，
                # 之后调用工具都走这一个会话，不再重启子进程。
                all_tools = await load_mcp_tools(self._session, server_name="amap")

                # 4. 把工具列表（一个 list）转成"名字 -> 工具对象"的字典。
                self.tools_map = {tool.name: tool for tool in all_tools}

                # 5. 标记初始化完成
                self._is_initialized = True

                print(f"✅ MCP 服务连接成功！已挂载 {len(self.tools_map)} 个高德地图工具（持久会话）:")
                # 遍历字典的 key（工具名），逐个打印出来
                for name in self.tools_map.keys():
                    print(f"   - {name}")

            except Exception as e:
                # 任何一步出错都会走到这里：清理半成品连接、重置标记、重新抛出
                await self._close_session()
                self._is_initialized = False
                print(f"❌ 启动 MCP 服务失败: {str(e)}")
                raise  # 不加参数的 raise = 把刚才的异常原样抛给调用方

    # ------------------------------------------------------------------
    # 关闭会话：退出持久会话，终止子进程
    # ------------------------------------------------------------------
    async def _close_session(self):
        """安全退出持久会话，终止 uvx 子进程。"""
        if self._session_cm is not None:
            try:
                # __aexit__(None, None, None) 是"异步上下文管理器"的退出方法。
                # 传三个 None 表示"没有异常发生"，让它正常收尾（关闭管道、结束子进程）。
                await self._session_cm.__aexit__(None, None, None)
            except Exception as e:
                print(f"⚠️ 关闭 MCP 会话异常: {str(e)}")
            # 清掉引用，让对象可以被垃圾回收
            self._session_cm = None
            self._session = None
        self.client = None

    # ------------------------------------------------------------------
    # 对外查询接口
    # ------------------------------------------------------------------
    def get_tool(self, tool_name: str) -> BaseTool:
        """根据工具名称获取工具对象。"""
        # 如果名字不在字典里，抛出 KeyError（Python 内置的"键不存在"异常）
        if tool_name not in self.tools_map:
            raise KeyError(
                # f"..." 是 f-string：花括号 {变量} 会被替换成它的值，方便拼字符串
                f"未找到 MCP 工具: '{tool_name}'。当前可用工具列表: {list(self.tools_map.keys())}"
            )
        # 用名字当 key 查字典，拿到工具对象
        return self.tools_map[tool_name]

    def get_all_tools(self) -> List[BaseTool]:
        """获取所有可用工具列表。"""
        # .values() 取出字典里所有"值"（工具对象），list() 再转成列表
        return list(self.tools_map.values())

    # ------------------------------------------------------------------
    # 统一调用入口
    # ------------------------------------------------------------------
    async def call_tool_text(self, tool_name: str, tool_input: dict) -> str:
        """统一调用一个 MCP 工具，并把返回结果整理成纯文本。

        Args:
            tool_name: 工具名，如 "maps_text_search"
            tool_input: 传给工具的参数字典，如 {"keywords": "故宫", "city": "北京"}

        Returns:
            工具返回的纯文本结果（str）
        """
        # 保险起见：如果还没初始化，先初始化
        if not self._is_initialized:
            await self.initialize()

        # 按名字拿到工具对象
        tool = self.get_tool(tool_name)

        # 加锁保护 stdio 会话并设置 15 秒超时，防止子进程 hang 死
        async with self._call_lock:
            result = await asyncio.wait_for(tool.ainvoke(tool_input), timeout=15.0)

        # ------- 解析返回结果 -------
        # 高德返回的数据格式不固定，可能是"内容块列表"、"字典"、或直接是字符串。
        # 下面这段就是"不管啥格式，都把纯文字抽出来"，统一返回一段 str。
        # isinstance(x, list) = 判断 x 是不是 list 类型。
        if isinstance(result, list):
            texts = []  # 收集所有文本片段
            for item in result:  # 遍历列表里的每一项
                if isinstance(item, dict) and "text" in item:
                    # 项是字典且含 "text" 键 → 直接取它的值
                    texts.append(item["text"])
                elif hasattr(item, "text"):
                    # hasattr(x, "text") = 判断 x 有没有 .text 这个属性
                    texts.append(str(item.text))
                else:
                    # 其他情况：直接把这一项转成字符串兜底
                    texts.append(str(item))
            # "\n".join(texts) 把所有片段用换行拼成一段文本
            return "\n".join(texts)
        elif isinstance(result, dict) and "text" in result:
            # result 本身是个字典，并且有 "text" 键
            return str(result["text"])
        # 兜底：把结果直接转成字符串返回
        return str(result)

    # ------------------------------------------------------------------
    # 收尾：应用关闭时调用
    # ------------------------------------------------------------------
    async def close(self):
        """关闭 MCP 客户端连接，终止持久会话子进程（收摊）。"""
        async with self._init_lock:   # 和 initialize 共用一把锁，避免边初始化边关闭
            await self._close_session()   # 真正关闭会话、终止子进程
            self.tools_map.clear()        # 清空工具字典
            self._is_initialized = False  # 标记为"未初始化"，下次可重新连接
            print("🔌 MCP 客户端连接已安全关闭。")


# ------------------------------------------------------------------
# 模块级快捷函数：让别的文件写 get_mcp_manager() 更短、更好记
# ------------------------------------------------------------------
def get_mcp_manager() -> MCPManager:
    """获取 MCP 管理器全局单例。"""
    return MCPManager.get_instance()
