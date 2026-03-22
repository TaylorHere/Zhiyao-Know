#!/usr/bin/env python3
"""
惠州电力局文件批量导入脚本

目录结构规则：
- 文件所在的文件夹名称忽略（如"1.法律法规"、"2.标准"等分类目录）
- 文件所在文件夹的上一级目录同时作为：最底层部门 + 知识库名称
- 再往上的所有层级都作为部门层级

示例（3层结构）：
文件汇总/
├── 17.数字化部（数据中心）/         # 一级部门
│   ├── 网络安全/                    # 二级部门 + 知识库名称
│   │   ├── 1.法律法规/              # ← 忽略，文件归入"网络安全"知识库
│   │   │   └── [文件]
│   │   └── 2.标准/                  # ← 忽略，文件归入"网络安全"知识库
│   │       └── [文件]
│   └── 通信运检/                    # 二级部门 + 知识库名称
│       └── ...

功能：
1. 解析目录层级，自动识别部门结构
2. 倒数第二层同时作为最底层部门和知识库名称
3. 最后一层（文件分类）忽略，文件直接归入上一级知识库
4. 使用 CommonRag/milvus 类型创建知识库

运行方式：
    python scripts/batch_import_huizhou.py [--dry-run]
"""

import argparse
import asyncio
import os
import re
import subprocess
from pathlib import Path

import httpx

# 配置
API_BASE_URL = os.getenv("YUXI_API_BASE_URL", "http://127.0.0.1:5050")
USERNAME = os.getenv("YUXI_TEST_USERNAME") or os.getenv("YUXI_SUPER_ADMIN_NAME") or "admin"
PASSWORD = os.getenv("YUXI_TEST_PASSWORD") or os.getenv("YUXI_SUPER_ADMIN_PASSWORD") or "Admin@123456"
PRESET_TOKEN = os.getenv("YUXI_TEST_TOKEN") or os.getenv("YUXI_ACCESS_TOKEN")
HTTP_TIMEOUT = float(os.getenv("YUXI_HTTP_TIMEOUT", "6000"))
LOGIN_RETRIES = int(os.getenv("YUXI_LOGIN_RETRIES", "20"))
SOURCE_DIR = "/mnt/usb2/4.文件汇总"

# 支持的文件类型
SUPPORTED_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt", ".xls", ".xlsx", ".ppt", ".pptx"}


def remove_prefix_number(name: str) -> str:
    """移除名称前的序号，如 '17.数字化部' -> '数字化部'"""
    return re.sub(r"^\d+\.\s*", "", name)


def get_directory_structure(root_path: str) -> dict:
    """
    解析目录结构，找出所有文件并确定其所属的部门层级和知识库
    
    规则：
    - 文件所在目录的名称忽略
    - 文件所在目录的父目录 = 最底层部门 + 知识库
    - 再往上的目录 = 上级部门
    
    返回格式：
    {
        "departments": [
            {
                "path": ["一级部门", "二级部门", ...],  # 部门层级路径
                "name": "最底层部门名",  # 同时也是知识库名
                "files": ["文件路径1", ...]
            }
        ]
    }
    """
    root = Path(root_path)
    result = {}  # key: 部门路径元组, value: 文件列表
    
    # 遍历所有文件
    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        if file_path.name.startswith("."):
            continue
        
        # 获取相对路径
        rel_path = file_path.relative_to(root)
        parts = list(rel_path.parts)
        
        # 至少需要3层：一级部门/二级部门(知识库)/分类/文件
        if len(parts) < 3:
            continue
        
        # 去掉最后两层：文件名 和 文件分类目录
        # 剩下的就是部门层级，最后一个部门同时作为知识库
        dept_parts = parts[:-2]  # 去掉 [分类目录, 文件名]
        
        # 清理部门名称（去除序号）
        clean_parts = tuple(remove_prefix_number(p) for p in dept_parts)
        
        if clean_parts not in result:
            result[clean_parts] = []
        result[clean_parts].append(str(file_path))
    
    # 转换为列表格式
    departments = []
    for dept_path, files in sorted(result.items()):
        departments.append({
            "path": list(dept_path),
            "name": dept_path[-1],  # 最后一级部门名就是知识库名
            "files": sorted(files)
        })
    
    return {"departments": departments}


class HuizhouImporter:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.token = None
        self.dept_id_cache = {}  # 部门路径 -> 部门ID
        self.kb_id_cache = {}    # 知识库名称 -> 知识库ID
        self.stats = {
            "departments": 0,
            "knowledge_bases": 0,
            "files_uploaded": 0,
            "files_failed": 0
        }
    
    async def login(self):
        """登录获取token"""
        print(f"\n{'='*60}")
        print(f"登录系统 (用户: {USERNAME})")
        print(f"{'='*60}")
        
        if self.dry_run:
            print("  [DRY-RUN] 跳过登录")
            return True

        if PRESET_TOKEN:
            self.token = PRESET_TOKEN
            if await self._validate_token():
                print("  ✅ 使用预设 token 登录成功")
                return True
            print("  ⚠️  预设 token 无效，尝试账号密码登录...")
        
        response = None
        last_error = None
        for attempt in range(1, LOGIN_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                    response = await client.post(
                        f"{API_BASE_URL}/api/auth/token",
                        data={"username": USERNAME, "password": PASSWORD}
                    )
                break
            except httpx.TimeoutException as exc:
                last_error = exc
                print(f"  ⚠️  登录超时 (第 {attempt}/{LOGIN_RETRIES} 次): {exc}")
            except Exception as exc:
                last_error = exc
                print(f"  ⚠️  登录请求异常 (第 {attempt}/{LOGIN_RETRIES} 次): {exc}")
            if attempt < LOGIN_RETRIES:
                await asyncio.sleep(1.5)

        if response is not None and response.status_code == 200:
            data = response.json()
            self.token = data["access_token"]
            print(f"  ✅ 登录成功 (角色: {data.get('role', 'unknown')})")
            return True

        if response is not None:
            print(f"  ⚠️  账号密码登录失败: {response.text}")
        elif last_error is not None:
            print(f"  ⚠️  账号密码登录最终失败: {last_error}")
        print("  尝试从本地 api 容器自动签发测试 token...")
        issued_token = self._issue_token_from_api_container()
        if issued_token:
            self.token = issued_token
            if await self._validate_token():
                print("  ✅ 自动签发 token 登录成功")
                return True
        print("  ❌ 自动获取 token 失败，请检查账号密码或容器环境")
        return False

    async def _validate_token(self) -> bool:
        """校验 token 是否可用"""
        if not self.token:
            return False
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{API_BASE_URL}/api/auth/me",
                    headers={"Authorization": f"Bearer {self.token}"}
                )
            return resp.status_code == 200
        except Exception:
            return False

    @staticmethod
    def _issue_token_from_api_container() -> str | None:
        """
        从本地 docker compose 的 api 容器签发临时 token
        依赖容器内 AuthUtils，默认签发 user_id=1
        """
        cmd = [
            "docker",
            "compose",
            "exec",
            "-T",
            "api",
            "python",
            "-c",
            "from server.utils.auth_utils import AuthUtils; print(AuthUtils.create_access_token({'sub':'1'}))",
        ]
        try:
            proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
            lines = [x.strip() for x in (proc.stdout or "").splitlines() if x.strip()]
            if not lines:
                return None
            return lines[-1]
        except Exception:
            return None
    
    def get_headers(self):
        """获取认证头"""
        return {"Authorization": f"Bearer {self.token}"}

    async def kb_exists(self, kb_id: str) -> bool:
        """检查知识库ID是否存在且可访问"""
        if self.dry_run:
            return True
        if not kb_id:
            return False
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{API_BASE_URL}/api/knowledge/databases/{kb_id}",
                headers=self.get_headers(),
            )
        return resp.status_code == 200

    async def ensure_valid_kb_id(self, kb_id: str, kb_name: str) -> str | None:
        """
        确保知识库ID有效。
        若传入kb_id不存在，则按知识库名称重新查询最新ID。
        """
        if self.dry_run:
            return kb_id
        if kb_id and await self.kb_exists(kb_id):
            return kb_id
        print(f"      ⚠️  知识库ID失效: {kb_id}，按名称重新查询: {kb_name}")
        refreshed_id = await self.get_kb_id(kb_name)
        if refreshed_id:
            print(f"      ✅ 已刷新知识库ID: {refreshed_id}")
        return refreshed_id
    
    async def ensure_department_hierarchy(self, dept_path: list[str]) -> int | None:
        """
        确保部门层级存在，返回最底层部门的ID
        
        dept_path: ["一级部门", "二级部门", "三级部门", ...]
        """
        parent_id = None
        
        for i, dept_name in enumerate(dept_path):
            # 构建当前层级的路径作为缓存键
            path_key = "/".join(dept_path[:i+1])
            
            if path_key in self.dept_id_cache:
                parent_id = self.dept_id_cache[path_key]
                continue
            
            # 需要创建这个部门
            indent = "  " * (i + 1)
            level_name = f"{'一二三四五六七八九十'[i]}级部门" if i < 10 else f"{i+1}级部门"
            print(f"{indent}创建{level_name}: {dept_name}" + (f" (父ID: {parent_id})" if parent_id else ""))
            
            dept_id = await self.create_department(dept_name, parent_id)
            
            if dept_id:
                self.dept_id_cache[path_key] = dept_id
                parent_id = dept_id
                self.stats["departments"] += 1
            else:
                return None
        
        return parent_id
    
    async def create_department(self, name: str, parent_id: int | None = None) -> int | None:
        """创建部门"""
        if self.dry_run:
            fake_id = abs(hash(f"{parent_id}_{name}")) % 10000
            print(f"      [DRY-RUN] 模拟ID: {fake_id}")
            return fake_id
        
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{API_BASE_URL}/api/departments",
                headers=self.get_headers(),
                json={
                    "name": name,
                    "parent_id": parent_id,
                    "description": f"惠州电力局 - {name}"
                }
            )
            
            # 创建成功返回 201
            if response.status_code in (200, 201):
                data = response.json()
                # API 返回格式: {"success": true, "data": {"id": ...}}
                if data.get("success") and data.get("data"):
                    dept_id = data["data"].get("id")
                    print(f"      ✅ 创建成功 (ID: {dept_id})")
                    return dept_id
                else:
                    print(f"      ⚠️  响应格式异常: {data}")
                    return await self.get_department_id(name, parent_id)
            elif response.status_code == 409 or "已存在" in response.text:
                print(f"      ⚠️  部门已存在，尝试获取ID...")
                return await self.get_department_id(name, parent_id)
            else:
                print(f"      ❌ 创建失败 (HTTP {response.status_code}): {response.text[:100]}")
                return None
    
    async def get_department_id(self, name: str, parent_id: int | None = None) -> int | None:
        """根据名称获取部门ID"""
        if self.dry_run:
            return abs(hash(f"{parent_id}_{name}")) % 10000
        
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{API_BASE_URL}/api/departments/tree",
                headers=self.get_headers()
            )
            
            if response.status_code == 200:
                data = response.json()
                # API 返回格式: {"success": true, "data": [{...}]}
                dept_list = data.get("data", []) if data.get("success") else []
                
                def find_dept(nodes, target_name, target_parent_id):
                    for node in nodes:
                        if node.get("name") == target_name:
                            if target_parent_id is None or node.get("parent_id") == target_parent_id:
                                return node.get("id")
                        children = node.get("children", [])
                        if children:
                            result = find_dept(children, target_name, target_parent_id)
                            if result:
                                return result
                    return None
                
                dept_id = find_dept(dept_list, name, parent_id)
                if dept_id:
                    print(f"      ✅ 找到部门 (ID: {dept_id})")
                return dept_id
        return None
    
    async def create_knowledge_base(self, name: str, dept_id: int, full_path: str) -> str | None:
        """创建知识库"""
        print(f"    创建知识库: {name} (关联部门ID: {dept_id})")
        
        if self.dry_run:
            fake_id = f"kb_{abs(hash(name)) % 100000:06x}"
            print(f"      [DRY-RUN] 模拟ID: {fake_id}")
            return fake_id
        
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{API_BASE_URL}/api/knowledge/databases",
                headers=self.get_headers(),
                json={
                    "database_name": name,
                    "description": f"惠州电力局 - {full_path}",
                    "embed_model_name": "siliconflow/BAAI/bge-m3",
                    "kb_type": "milvus",
                    "additional_params": {},
                    "share_config": {
                        "is_shared": True,
                        "accessible_departments": [dept_id]
                    }
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                kb_id = data.get("db_id")
                print(f"      ✅ 创建成功 (ID: {kb_id})")
                await self.add_kb_department(kb_id, dept_id)
                return kb_id
            elif response.status_code == 409 or "已存在" in response.text:
                print(f"      ⚠️  知识库已存在，尝试获取ID...")
                return await self.get_kb_id(name)
            else:
                print(f"      ❌ 创建失败: {response.text[:100]}")
                return None
    
    async def add_kb_department(self, kb_id: str, dept_id: int):
        """添加知识库部门关联"""
        if self.dry_run:
            return
        
        async with httpx.AsyncClient(timeout=30) as client:
            await client.post(
                f"{API_BASE_URL}/api/kb-manage/{kb_id}/departments",
                headers=self.get_headers(),
                json={"department_ids": [dept_id]}  # API 需要数组
            )
    
    async def get_kb_id(self, name: str) -> str | None:
        """根据名称获取知识库ID"""
        if self.dry_run:
            return f"kb_{abs(hash(name)) % 100000:06x}"
        
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{API_BASE_URL}/api/knowledge/databases",
                headers=self.get_headers()
            )
            
            if response.status_code == 200:
                data = response.json()
                for db in data.get("databases", []):
                    if db.get("name") == name:
                        print(f"      ✅ 找到知识库 (ID: {db.get('db_id')})")
                        return db.get("db_id")
        return None
    
    async def get_file_meta_by_filename(self, kb_id: str, filename: str) -> dict | None:
        """在知识库中按文件名查找文件元数据"""
        if self.dry_run:
            return None

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{API_BASE_URL}/api/knowledge/databases/{kb_id}",
                headers=self.get_headers(),
            )
            if response.status_code != 200:
                return None

            data = response.json() or {}
            files = data.get("files") or {}
            for file_id, meta in files.items():
                if meta.get("filename") == filename or meta.get("original_filename") == filename:
                    return {
                        "file_id": file_id,
                        "status": meta.get("status"),
                        "filename": meta.get("filename") or filename,
                    }
        return None

    async def upload_file(self, kb_id: str, file_path: str) -> dict | None:
        """上传文件到知识库，返回上传结果字典"""
        filename = os.path.basename(file_path)
        short_name = filename[:40] + "..." if len(filename) > 40 else filename
        print(f"      上传: {short_name}")
        
        if self.dry_run:
            print(f"        [DRY-RUN] 跳过上传")
            return {"kind": "uploaded", "minio_path": f"minio://fake/{filename}", "content_hash": "fake_hash"}
        
        try:
            file_size = os.path.getsize(file_path)
            file_size_mb = file_size / (1024 * 1024)
            print(f"      上传: {short_name} ({file_size_mb:.2f} MB)")
            
            # 重试机制
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    async with httpx.AsyncClient(timeout=300) as client:
                        with open(file_path, "rb") as f:
                            files = {"file": (filename, f)}
                            response = await client.post(
                                f"{API_BASE_URL}/api/knowledge/files/upload?db_id={kb_id}",
                                headers=self.get_headers(),
                                files=files
                            )
                        
                        if response.status_code == 200:
                            data = response.json()
                            minio_path = data.get("file_path") or data.get("minio_path")
                            content_hash = data.get("content_hash")
                            print(f"        ✅ 上传成功")
                            self.stats["files_uploaded"] += 1
                            return {
                                "kind": "uploaded",
                                "minio_path": minio_path,
                                "content_hash": content_hash,
                                "filename": filename,
                            }
                        elif response.status_code == 409:
                            existing = await self.get_file_meta_by_filename(kb_id, filename)
                            if existing:
                                print(
                                    f"        ⚠️  文件已存在，加入补漏队列 "
                                    f"(file_id={existing['file_id']}, status={existing['status']})"
                                )
                                return {"kind": "existing", **existing}
                            print(f"        ⚠️  文件已存在，但未查到对应记录，跳过")
                            return None
                        else:
                            print(f"        ❌ 上传失败 (尝试 {attempt+1}/{max_retries}): {response.status_code} - {response.text[:200]}")
                except Exception as e:
                    print(f"        ❌ 上传异常 (尝试 {attempt+1}/{max_retries}): {type(e).__name__}: {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2)
                        continue
            
            self.stats["files_failed"] += 1
            return None
        except Exception as e:
            print(f"        ❌ 文件处理异常: {type(e).__name__}: {e}")
            self.stats["files_failed"] += 1
            return None

    async def retry_existing_files(self, kb_id: str, existing_files: list[dict]):
        """对已存在但失败状态的文件进行补漏（parse/index）"""
        if self.dry_run or not existing_files:
            return

        parse_ids = []
        index_ids = []
        for item in existing_files:
            file_id = item.get("file_id")
            status = (item.get("status") or "").lower()
            if not file_id:
                continue
            if status in {"uploaded", "error_parsing", "failed", "parsing"}:
                parse_ids.append(file_id)
            elif status in {"parsed", "error_indexing", "indexing", "done"}:
                index_ids.append(file_id)

        async with httpx.AsyncClient(timeout=120) as client:
            if parse_ids:
                resp = await client.post(
                    f"{API_BASE_URL}/api/knowledge/databases/{kb_id}/documents/parse",
                    headers=self.get_headers(),
                    json=parse_ids,
                )
                if resp.status_code == 200:
                    task_id = resp.json().get("task_id", "unknown")
                    print(f"      ✅ 补漏解析任务已提交 (task_id: {task_id}, files={len(parse_ids)})")
                else:
                    print(f"      ❌ 补漏解析提交失败: {resp.text[:120]}")

            # parse 后统一走 index（已 parsed / error_indexing / 本次parse的文件）
            retry_index_ids = list(dict.fromkeys(index_ids + parse_ids))
            if retry_index_ids:
                resp = await client.post(
                    f"{API_BASE_URL}/api/knowledge/databases/{kb_id}/documents/index",
                    headers=self.get_headers(),
                    json={
                        "file_ids": retry_index_ids,
                        "params": {"chunk_size": 1000, "chunk_overlap": 200, "qa_separator": ""},
                    },
                )
                if resp.status_code == 200:
                    task_id = resp.json().get("task_id", "unknown")
                    print(f"      ✅ 补漏入库任务已提交 (task_id: {task_id}, files={len(retry_index_ids)})")
                else:
                    print(f"      ❌ 补漏入库提交失败: {resp.text[:120]}")

    async def add_documents_to_kb(self, kb_id: str, kb_name: str, file_infos: list[dict]):
        """将上传的文件添加到知识库并入库
        
        Args:
            kb_id: 知识库ID
            kb_name: 知识库名称（用于ID失效时重查）
            file_infos: 上传结果列表
        """
        if not file_infos:
            return
        
        print(f"    添加并入库 {len(file_infos)} 个文件...")
        
        if self.dry_run:
            print(f"      [DRY-RUN] 跳过入库")
            return
        
        # 构建 content_hashes 映射
        items = []
        content_hashes = {}
        existing_files = []
        for item in file_infos:
            if item.get("kind") == "uploaded":
                minio_path = item.get("minio_path")
                content_hash = item.get("content_hash")
                if minio_path and content_hash:
                    items.append(minio_path)
                    content_hashes[minio_path] = content_hash
            elif item.get("kind") == "existing":
                existing_files.append(item)
        
        try:
            kb_id = await self.ensure_valid_kb_id(kb_id, kb_name)
            if not kb_id:
                print(f"      ❌ 入库失败：知识库不存在 (name={kb_name})")
                return

            async with httpx.AsyncClient(timeout=600) as client:
                response = None
                if items:
                    response = await client.post(
                        f"{API_BASE_URL}/api/knowledge/databases/{kb_id}/documents",
                        headers=self.get_headers(),
                        json={
                            "items": items,
                            "params": {
                                "auto_index": True,
                                "content_hashes": content_hashes
                            }
                        }
                    )
                
                if response is not None and response.status_code == 200:
                    data = response.json()
                    task_id = data.get("task_id", "unknown")
                    print(f"      ✅ 入库任务已提交 (task_id: {task_id})")
                elif response is not None and (response.status_code == 404 or "not found" in response.text.lower()):
                    # 处理数据库ID漂移：按名称重查后重试一次
                    print(f"      ⚠️  入库返回 not found，尝试刷新知识库ID后重试...")
                    refreshed_kb_id = await self.ensure_valid_kb_id("", kb_name)
                    if refreshed_kb_id and refreshed_kb_id != kb_id:
                        retry_resp = await client.post(
                            f"{API_BASE_URL}/api/knowledge/databases/{refreshed_kb_id}/documents",
                            headers=self.get_headers(),
                            json={
                                "items": items,
                                "params": {
                                    "auto_index": True,
                                    "content_hashes": content_hashes
                                }
                            }
                        )
                        if retry_resp.status_code == 200:
                            data = retry_resp.json()
                            task_id = data.get("task_id", "unknown")
                            print(f"      ✅ 重试入库成功 (task_id: {task_id})")
                            await self.retry_existing_files(refreshed_kb_id, existing_files)
                            return
                        print(f"      ❌ 重试入库失败: {retry_resp.text[:100]}")
                    else:
                        print(f"      ❌ 无法刷新到有效知识库ID，重试终止")
                elif response is not None:
                    print(f"      ❌ 入库失败: {response.text[:100]}")

                if existing_files:
                    await self.retry_existing_files(kb_id, existing_files)
        except Exception as e:
            print(f"      ❌ 入库异常: {e}")
    
    async def run(self):
        """执行导入"""
        print("\n" + "="*60)
        print("惠州电力局文件批量导入")
        print("="*60)
        print(f"源目录: {SOURCE_DIR}")
        print(f"模式: {'DRY-RUN (仅预览)' if self.dry_run else '实际执行'}")
        
        # 1. 解析目录结构
        print("\n" + "-"*60)
        print("步骤 1: 解析目录结构")
        print("-"*60)
        
        structure = get_directory_structure(SOURCE_DIR)
        departments = structure["departments"]
        
        # 统计
        unique_depts = set()
        for d in departments:
            for i in range(len(d["path"])):
                unique_depts.add("/".join(d["path"][:i+1]))
        
        total_kbs = len(departments)
        total_files = sum(len(d["files"]) for d in departments)
        
        print(f"  部门数量: {len(unique_depts)} 个")
        print(f"  知识库数量: {total_kbs} 个")
        print(f"  文件数量: {total_files} 个")
        
        # 显示部门层级
        print("\n  部门层级预览:")
        shown_paths = set()
        for d in departments[:10]:  # 只显示前10个
            for i in range(len(d["path"])):
                path_key = "/".join(d["path"][:i+1])
                if path_key not in shown_paths:
                    shown_paths.add(path_key)
                    indent = "  " * (i + 2)
                    level = f"L{i+1}"
                    is_kb = i == len(d["path"]) - 1
                    suffix = " [知识库]" if is_kb else ""
                    print(f"{indent}{level}: {d['path'][i]}{suffix}")
        if len(departments) > 10:
            print(f"    ... 等共 {total_kbs} 个知识库")
        
        # 2. 登录
        if not await self.login():
            return
        
        # 3. 创建部门和知识库
        print("\n" + "-"*60)
        print("步骤 2: 创建部门和知识库")
        print("-"*60)
        
        for dept_info in departments:
            dept_path = dept_info["path"]
            kb_name = dept_info["name"]
            files = dept_info["files"]
            full_path = " > ".join(dept_path)
            
            print(f"\n[知识库] {full_path}")
            
            # 确保部门层级存在
            dept_id = await self.ensure_department_hierarchy(dept_path)
            
            if not dept_id:
                print(f"  ⚠️  跳过（部门创建失败）")
                continue
            
            # 创建知识库
            kb_id = await self.create_knowledge_base(kb_name, dept_id, full_path)
            
            if not kb_id:
                print(f"  ⚠️  跳过（知识库创建失败）")
                continue

            kb_id = await self.ensure_valid_kb_id(kb_id, kb_name)
            if not kb_id:
                print(f"  ⚠️  跳过（知识库ID失效且无法刷新）")
                continue
            
            self.kb_id_cache[kb_name] = kb_id
            self.stats["knowledge_bases"] += 1
            
            # 上传文件
            file_infos = []  # [(minio_path, content_hash), ...]
            for file_path in files:
                result = await self.upload_file(kb_id, file_path)
                if result:
                    file_infos.append(result)
                
                if not self.dry_run:
                    await asyncio.sleep(2.0)  # 增加延时到2秒，避免请求过快
            
            # 添加文档并入库
            if file_infos:
                await self.add_documents_to_kb(kb_id, kb_name, file_infos)
        
        # 4. 完成
        print("\n" + "="*60)
        print("导入完成")
        print("="*60)
        print(f"  部门: {self.stats['departments']} 个")
        print(f"  知识库: {self.stats['knowledge_bases']} 个")
        if not self.dry_run:
            print(f"  文件上传成功: {self.stats['files_uploaded']} 个")
            print(f"  文件上传失败: {self.stats['files_failed']} 个")


async def main():
    parser = argparse.ArgumentParser(description="惠州电力局文件批量导入")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不实际执行")
    args = parser.parse_args()
    
    importer = HuizhouImporter(dry_run=args.dry_run)
    await importer.run()


if __name__ == "__main__":
    asyncio.run(main())
