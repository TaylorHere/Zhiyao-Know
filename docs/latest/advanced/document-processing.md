# 文档处理与 OCR

系统提供 5 种文档处理选项：

- **RapidOCR**: CPU 友好，无需 GPU，适合基础文字识别
- **MinerU**: 本地化高精度 VLM 解析，适合复杂 PDF 和表格文档
- **MinerU Official**: 官方云服务 API，无需本地部署，开箱即用
- **PP-StructureV3**: 结构化解析，适合表格、票据等特殊格式
- **DeepSeek OCR**: 基于 SiliconFlow API 的 DeepSeek OCR OCR 服务

## 支持的文件类型

### 常规文档格式
- **文本文档**: `.txt`, `.md`, `.html`, `.htm`
- **Word 文档**: `.docx`
- **PDF 文档**: `.pdf`
- **电子表格**: `.csv`, `.xls`, `.xlsx`
- **JSON 数据**: `.json`

::: tip 图片显示
文档中的图片会自动上传到对象存储并替换为可访问的 URL。但是如果想要在外部正常显示图片，需要配置 `HOST_IP` 环境变量，将其设置为您的服务器 IP 地址。
:::

### 图像格式（需要 OCR）
- **常见图片**: `.jpg`, `.jpeg`, `.png`, `.bmp`, `.tiff`, `.tif`, `.gif`, `.webp`

### ZIP 压缩包
- **ZIP 文档**: `.zip` - 支持包含 Markdown 文件和图片的压缩包
  - 自动提取和处理 ZIP 包中的 `.md` 文件
  - 自动处理 ZIP 包中的图片文件并上传到对象存储（MINIO）
  - 图片链接会自动替换为可访问的 URL
  - 优先处理名为 `full.md` 的文件，否则使用第一个 `.md` 文件
  - 支持图片目录的智能识别（`images/`、`../images/` 等）

### URL 网页内容
- **网页链接**: `http://` 或 `https://`
  - 自动抓取网页 HTML 内容并转换为 Markdown
  - **白名单机制**: 出于安全考虑，必须配置环境变量 `YUXI_URL_WHITELIST` 才能使用此功能
  - **内网保护**: 默认禁止抓取私有 IP 地址（如 127.0.0.1, 192.168.x.x）
  - **去重机制**: 自动检测 URL 是否已存在，以及内容 Hash 是否重复

::: tip URL 白名单配置
在 `.env` 文件中配置允许抓取的域名列表，用逗号分隔。支持通配符。
例如：`YUXI_URL_WHITELIST=github.com,*.wikipedia.org,docs.python.org`
:::



## 快速配置

### 1. 基础 OCR (RapidOCR)

```bash
# 下载模型
hf download SWHL/RapidOCR --local-dir ./models/SWHL/RapidOCR

# 启动服务
docker compose up -d api
```

需要确保 `MODEL_DIR` 环境变量指向 RapidOCR 上层目录，例如 `./models`。

### 2. 高精度 OCR (MinerU)

需要在 `.env` 文件中配置：

```bash
MINERU_VL_SERVER=http://localhost:30000  # 对应 docker compose 中的 mineru-vllm-server 服务
MINERU_API_URI=http://localhost:30001  # 对应 docker compose 中的 mineru-api 服务
```

然后启动相关服务

```bash
# 需要 GPU，启动 MinerU 服务
docker compose up mineru-vllm-server mineru-api -d

# 启动主服务
docker compose up api -d
```

::: tip 处理超时
文档解析超时时间默认 1800 秒，可通过 `MINERU_TIMEOUT` 环境变量调整。
:::


### 3. 官方云服务 (MinerU Official)

API 密钥可以从 [MinerU 官网](https://mineru.net) 申请。

然后在 `.env` 文件中添加

```bash
# 设置 API 密钥环境变量
MINERU_API_KEY="your-api-key-here"
```

然后使用 `docker compose up api -d` 重启后端服务。

### 4. 结构化解析 (PP-StructureV3)

```bash
# 需要 GPU，启动 PP-StructureV3 服务
docker compose up -d paddlex

# 启动主服务
docker compose up -d api
```

### 5. DeepSeek OCR (SiliconFlow)

DeepSeek OCR 基于 SiliconFlow API，提供智能文档理解和 Markdown 格式输出。

API 密钥可以从 [SiliconFlow](https://cloud.siliconflow.cn/i/Eo5yTHGJ) 申请。

然后在 `.env` 文件中添加：

```bash
# 设置 SiliconFlow API 密钥
SILICONFLOW_API_KEY="your-api-key-here"
```

重启后端服务即可使用：

```bash
docker compose restart api
```

注：当前还不支持保存其中的图片信息，mineru 当前版本已支持。

## 处理器选择

| 处理器 | 适用场景 | 硬件要求 | 特点 |
|--------|----------|------------|------|
| **RapidOCR** | 基础文字识别 | CPU | 速度快，资源占用低 |
| **MinerU** | 复杂 PDF、表格、公式 | GPU | 精度高，版面分析好 |
| **MinerU Official** | 复杂文档解析（云服务） | 无特殊要求 | 官方云服务，开箱即用，有 API 配额 |
| **PP-StructureV3** | 表格、票据、结构化文档 | GPU | 专业版面解析 |
| **DeepSeek OCR** | 智能文档理解和 Markdown 输出 | 无特殊要求 | 云端服务 |

## 参数说明

### enable_ocr 选项

对应网页中的 `使用 OCR` 选项

- `disable`: 不启用 OCR（PDF 按文本提取，图片**必须选择 OCR 方式**）
- `onnx_rapid_ocr`: RapidOCR 处理
- `mineru_ocr`: MinerU HTTP API 处理
- `mineru_official`: MinerU 官方云服务 API 处理
- `paddlex_ocr`: PP-StructureV3 处理
- `deepseek_ocr`: DeepSeek OCR（SiliconFlow API）处理

### 注意事项
- **图片文件必须启用 OCR**，否则无法提取内容
- MinerU 和 PP-StructureV3 需要 GPU 支持
- MinerU Official 需要设置 `MINERU_API_KEY` 环境变量
- DeepSeek OCR 需要设置 `SILICONFLOW_API_KEY` 环境变量
- RapidOCR 适合 CPU 环境和基础识别需求

## 入库并发参数（新增）

为提升“批量提交文件”时的入库速度，系统支持在入库阶段设置并发度。

### 1) 单次请求参数：`index_concurrency`

- 作用范围：当前一次入库任务
- 适用接口：
  - `POST /api/knowledge/databases/{db_id}/documents`（开启 `auto_index=true` 时）
  - `POST /api/knowledge/databases/{db_id}/documents/index`
- 类型：整数，最小值 1

示例（上传后自动解析+自动入库）：

```json
{
  "items": ["http://localhost:9000/ref-kb-xxx/a.pdf"],
  "params": {
    "content_type": "file",
    "auto_index": true,
    "chunk_size": 1000,
    "chunk_overlap": 200,
    "qa_separator": "",
    "index_concurrency": 4
  }
}
```

示例（手动批量入库）：

```json
{
  "file_ids": ["file_a", "file_b", "file_c"],
  "params": {
    "chunk_size": 1000,
    "chunk_overlap": 200,
    "qa_separator": "",
    "index_concurrency": 4
  }
}
```

### 2) 全局默认参数：`YUXI_INDEX_CONCURRENCY`

- 作用范围：未传 `index_concurrency` 时的默认并发度
- 默认值：`4`

```bash
YUXI_INDEX_CONCURRENCY=4
```

### 3) 任务调度并发（服务级）

- `YUXI_API_WORKERS`：API 进程数（Uvicorn workers，默认 `4`）
- `YUXI_TASK_WORKER_COUNT`：每个 API 进程内 Tasker worker 数（默认 `8`）

建议先从以下组合开始压测：

- 中等机器：`YUXI_API_WORKERS=2`、`YUXI_TASK_WORKER_COUNT=4`、`index_concurrency=2~4`
- 高配机器：`YUXI_API_WORKERS=4`、`YUXI_TASK_WORKER_COUNT=8`、`index_concurrency=4~8`

### 4) 使用建议

- 文档较小或大量空文本分块时，并发收益有限。
- 文档较大且分块较多时，提高 `index_concurrency` 收益更明显。
- 建议逐步调大并发，观察 CPU、内存、向量库与嵌入服务负载，避免过载。

## 惠州批量导入脚本用法

脚本路径：`scripts/batch_import_huizhou.py`

### 快速示例

仅预览目录结构（不创建部门、不上传文件）：

```bash
python scripts/batch_import_huizhou.py --dry-run
```

实际导入（上传并发 + 入库提交并发 + 自动入库）：

```bash
python scripts/batch_import_huizhou.py \
  --upload-concurrency 4 \
  --ingest-concurrency 2 \
  --ingest-batch-size 30 \
  --index-concurrency 2
```

仅上传与解析，不自动入库：

```bash
python scripts/batch_import_huizhou.py --no-auto-index
```

### 参数详细说明

- `--dry-run`
  - 类型：开关
  - 默认：关闭
  - 作用：只打印将要处理的部门/知识库/文件，不执行实际 API 调用。

- `--concurrency`
  - 类型：整数
  - 默认：`1`
  - 作用：兼容旧参数，等同 `--upload-concurrency`。建议新任务优先使用 `--upload-concurrency`。

- `--upload-concurrency`
  - 类型：整数（>=1）
  - 默认：未传时继承 `--concurrency`
  - 作用：单个知识库内“文件上传”并发数。

- `--ingest-concurrency`
  - 类型：整数（>=1）
  - 默认：`1`
  - 作用：`/documents` 入库任务提交并发数（提交 API 的并发，不是模型推理并发）。

- `--ingest-batch-size`
  - 类型：整数（>=1）
  - 默认：`50`
  - 作用：每次调用 `/documents` 时携带的文件数量。大批次减少任务条数，小批次更稳健。

- `--index-concurrency`
  - 类型：整数（>=1）
  - 默认：`2`
  - 作用：透传到后端 `params.index_concurrency`，控制单任务内入库并发。
  - 建议：若嵌入模型来自外部 API（例如 SiliconFlow），建议从 `1~2` 起步，避免触发 429 限流。

- `--no-auto-index`
  - 类型：开关
  - 默认：关闭（默认自动入库开启）
  - 作用：关闭自动入库，仅执行上传+解析。

### 脚本行为说明

- 自动跳过隐藏文件和 Office 临时锁文件（如 `~$xxx.docx`）。
- 若文件已存在，会进入补漏流程：
  - `uploaded/error_parsing/failed/parsing`：补解析
  - `parsed/error_indexing/indexing/done`：补入库

### 推荐并发策略

- 首次导入或外部嵌入服务有限流时：
  - `--upload-concurrency 2`
  - `--ingest-concurrency 1`
  - `--ingest-batch-size 20~30`
  - `--index-concurrency 1~2`

- 本地嵌入服务、机器资源充足时：
  - `--upload-concurrency 4~8`
  - `--ingest-concurrency 2~4`
  - `--ingest-batch-size 30~80`
  - `--index-concurrency 3~6`
