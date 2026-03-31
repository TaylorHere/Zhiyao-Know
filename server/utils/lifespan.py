from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.services.task_service import tasker
from src.services.mcp_service import init_mcp_servers
from src.services.first_run_seed_service import FirstRunSeedService
from src.services.jingzhou_compliance_seed_service import JingzhouComplianceSeedService
from src.services.kb_startup_recovery_service import recover_interrupted_kb_tasks_on_startup
from src.storage.postgres.manager import pg_manager
from src.knowledge import knowledge_base
from src.utils import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan事件管理器"""
    # 初始化数据库连接
    try:
        pg_manager.initialize()
        await pg_manager.create_business_tables()
        await pg_manager.ensure_knowledge_schema()
    except Exception as e:
        logger.error(f"Failed to initialize database during startup: {e}")

    # 初始化 MCP 服务器配置
    try:
        await init_mcp_servers()
    except Exception as e:
        logger.error(f"Failed to initialize MCP servers during startup: {e}")

    # 初始化知识库管理器
    try:
        await knowledge_base.initialize()
    except Exception as e:
        logger.error(f"Failed to initialize knowledge base manager: {e}")

    # 启动自检：打印荆州营销隐藏库与智能体绑定状态
    try:
        await FirstRunSeedService.log_startup_binding_status()
    except Exception as e:
        logger.error(f"Failed to run HuizhouPowerQA startup binding check: {e}")

    await tasker.start()

    # 启动恢复：服务重启后自动修复并补跑中断的知识库解析/入库任务
    try:
        await recover_interrupted_kb_tasks_on_startup()
    except Exception as e:
        logger.error(f"Failed to recover interrupted KB tasks on startup: {e}")

    # 启动导入：荆州一库两清单（存在种子文件时自动触发）
    try:
        await JingzhouComplianceSeedService.enqueue_startup_seed(operator_id=1, department_id=1)
    except Exception as e:
        logger.error(f"Failed to enqueue jingzhou compliance seed task: {e}")

    yield
    await tasker.shutdown()
    await pg_manager.close()
