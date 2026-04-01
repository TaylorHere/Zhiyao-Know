# 合规风险中心与并发任务环境变量说明

本文档给运维同学使用，聚焦本次功能相关的环境变量：

1. 合规风险中心（一库两清单）自动种子导入参数
2. API 多 worker 与任务并发参数
3. 启动后中断任务自动恢复参数

## 一、合规风险中心种子导入参数

以下变量由 `src/services/jingzhou_compliance_seed_service.py` 使用。

| 变量名 | 默认值 | 说明 | 是否必配 |
| --- | --- | --- | --- |
| `YUXI_JINGZHOU_COMPLIANCE_AUTO_SEED` | `true` | API 启动时是否自动触发“一库两清单”导入任务 | 否 |
| `YUXI_JINGZHOU_COMPLIANCE_SOURCE_DIR` | 自动探测 | Excel 源目录。建议生产明确配置，避免路径歧义 | 建议 |
| `YUXI_JINGZHOU_COMPLIANCE_FORCE` | `false` | 自动导入时是否强制重跑已存在文件（重解析/重入库） | 否 |
| `YUXI_JINGZHOU_COMPLIANCE_CHUNK_SIZE` | `2200` | 导入后文档切分 `chunk_size` | 否 |
| `YUXI_JINGZHOU_COMPLIANCE_CHUNK_OVERLAP` | `200` | 导入后文档切分 `chunk_overlap` | 否 |
| `YUXI_JINGZHOU_COMPLIANCE_INDEX_CONCURRENCY` | `4` | 单次导入任务内入库并发 | 否 |
| `YUXI_JINGZHOU_COMPLIANCE_SEARCH_MODE` | `hybrid` | 初始化时写入知识库的默认检索模式 | 否 |
| `YUXI_JINGZHOU_COMPLIANCE_TOP_K` | `8` | 初始化时写入知识库的默认 `top_k` | 否 |
| `YUXI_JINGZHOU_COMPLIANCE_KEYWORD_TOP_K` | `30` | 初始化时写入知识库的默认 `keyword_top_k` | 否 |

### 生产建议

- 首次上线建议：
  - `YUXI_JINGZHOU_COMPLIANCE_AUTO_SEED=false`
  - 服务稳定后，由管理员在页面手工导入 Excel 或执行脚本导入
- 避免误重跑：
  - `YUXI_JINGZHOU_COMPLIANCE_FORCE=false`
- 推荐检索参数：
  - `YUXI_JINGZHOU_COMPLIANCE_SEARCH_MODE=hybrid`
  - `YUXI_JINGZHOU_COMPLIANCE_TOP_K=8`
  - `YUXI_JINGZHOU_COMPLIANCE_KEYWORD_TOP_K=30`

## 二、API 多 worker 与任务并发参数

以下变量主要在 `docker-compose.yaml`、`src/services/task_service.py`、`server/routers/knowledge_router.py` 中生效。

| 变量名 | 默认值 | 说明 | 是否需要重启 API |
| --- | --- | --- | --- |
| `YUXI_API_WORKERS` | `1` | Uvicorn worker 数量（多进程） | 是 |
| `YUXI_TASK_WORKER_COUNT` | `1` | 后台任务 worker 数量（应用内任务并发） | 是 |
| `YUXI_INDEX_CONCURRENCY` | `1` | 文档入库默认并发（接口未显式传参时） | 是 |

### 调参建议（先小步）

- 4 核机器起步：
  - `YUXI_API_WORKERS=2`
  - `YUXI_TASK_WORKER_COUNT=2`
  - `YUXI_INDEX_CONCURRENCY=2`
- 8 核机器起步：
  - `YUXI_API_WORKERS=3`
  - `YUXI_TASK_WORKER_COUNT=3`
  - `YUXI_INDEX_CONCURRENCY=3`

> 不建议一次性拉满，先观察 CPU、内存、Milvus 延迟、任务失败率再逐步上调。

## 三、解析队列一致性与恢复参数

以下变量对应 Redis 队列与启动恢复能力。

| 变量名 | 默认值 | 说明 | 是否需要重启 API |
| --- | --- | --- | --- |
| `YUXI_PROCESSING_QUEUE_REDIS_URL` | `redis://kb-queue-redis:6379/0` | 跨 worker 共享处理队列 | 是 |
| `YUXI_PROCESSING_QUEUE_REDIS_TIMEOUT` | `1.0` | Redis 超时时间（秒） | 是 |
| `YUXI_PROCESSING_STALE_SECONDS` | `600` | 处理中状态判定为陈旧的阈值（秒） | 是 |
| `YUXI_STARTUP_AUTO_RECOVER_INTERRUPTED` | `true` | 服务启动后是否自动补跑中断任务 | 是 |
| `YUXI_STARTUP_RECOVER_MAX_FILES` | `20` | 每次启动恢复最大文件数 | 是 |
| `YUXI_STARTUP_RECOVER_BATCH_SIZE` | `10` | 每批提交恢复任务数 | 是 |
| `YUXI_STARTUP_RECOVER_LOOKBACK_HOURS` | `6` | 向前扫描中断任务时间窗（小时） | 是 |

### 生产建议

- 多 worker 必须配置：
  - `YUXI_PROCESSING_QUEUE_REDIS_URL` 指向可用 Redis
- 重启频繁场景建议：
  - `YUXI_STARTUP_AUTO_RECOVER_INTERRUPTED=true`
  - `YUXI_STARTUP_RECOVER_MAX_FILES` 设为 `50`（按业务量调整）

## 四、推荐生产配置片段

```dotenv
# API 并发
YUXI_API_WORKERS=3
YUXI_TASK_WORKER_COUNT=3
YUXI_INDEX_CONCURRENCY=3

# 共享处理队列
YUXI_PROCESSING_QUEUE_REDIS_URL=redis://kb-queue-redis:6379/0
YUXI_PROCESSING_QUEUE_REDIS_TIMEOUT=1.0
YUXI_PROCESSING_STALE_SECONDS=600

# 启动恢复
YUXI_STARTUP_AUTO_RECOVER_INTERRUPTED=true
YUXI_STARTUP_RECOVER_MAX_FILES=50
YUXI_STARTUP_RECOVER_BATCH_SIZE=10
YUXI_STARTUP_RECOVER_LOOKBACK_HOURS=12

# 一库两清单（建议生产首发关闭自动导入）
YUXI_JINGZHOU_COMPLIANCE_AUTO_SEED=false
YUXI_JINGZHOU_COMPLIANCE_SOURCE_DIR=/data/yuxi/compliance-source
YUXI_JINGZHOU_COMPLIANCE_FORCE=false
YUXI_JINGZHOU_COMPLIANCE_CHUNK_SIZE=2200
YUXI_JINGZHOU_COMPLIANCE_CHUNK_OVERLAP=200
YUXI_JINGZHOU_COMPLIANCE_INDEX_CONCURRENCY=4
YUXI_JINGZHOU_COMPLIANCE_SEARCH_MODE=hybrid
YUXI_JINGZHOU_COMPLIANCE_TOP_K=8
YUXI_JINGZHOU_COMPLIANCE_KEYWORD_TOP_K=30
```

## 五、变更生效方式

1. 修改 `.env` 或部署平台环境变量
2. 重启 `api` 服务（必要）
3. 通过日志确认配置已生效：
   - API worker 启动数
   - task worker 启动数
   - Redis 处理队列连接日志
   - 启动恢复任务日志
