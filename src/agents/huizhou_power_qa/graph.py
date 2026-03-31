from langchain.agents import create_agent
from langchain.agents.middleware import ModelRetryMiddleware

from src.agents.common import BaseAgent, load_chat_model
from src.agents.common.middlewares import RuntimeConfigMiddleware, inject_attachment_context
from src.services.mcp_service import get_tools_from_all_servers
from .context import HuizhouPowerQAContext


class HuizhouPowerQAAgent(BaseAgent):
    name = "荆州电力整改问答助手"
    description = "基于荆州电力整改方案 QA 知识库进行问答的专用智能体。"
    capabilities = ["file_upload"]
    context_schema = HuizhouPowerQAContext

    async def get_graph(self, **kwargs):
        context = self.context_schema()
        all_mcp_tools = await get_tools_from_all_servers()

        graph = create_agent(
            model=load_chat_model(context.model),
            middleware=[
                inject_attachment_context,
                ModelRetryMiddleware(),
                RuntimeConfigMiddleware(extra_tools=all_mcp_tools),
            ],
            checkpointer=await self._get_checkpointer(),
        )

        return graph
