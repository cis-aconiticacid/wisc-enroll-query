# UW-Madison Course Selection Toolkit

UW-Madison 选课工具集。核心是把 **enroll.wisc.edu 搜索**（官方选课 API）和
**Madgrades 历史 GPA** 两个独立数据源打通：搜到的每门课自动附带历史平均 GPA，
并按 GPA 从高到低排序。

包含四个层次：

1. **GPA Ranker** (`gpa_ranker.py`) — Madgrades API 客户端，输入课号返回加权 GPA，内置缓存 + 限流。
2. **Course Search Client** (`course_search.py`) — 逆向自 enroll.wisc.edu 前端的 ES 查询客户端，支持完整筛选/详情/enrollment packages。
3. **Bridge** (`search_with_gpa.py`) — 并发给搜索结果附加 GPA，分桶排序（有数据 vs 无数据）。
4. **Web App** (`api/` + `web/`) — FastAPI 后端 + Vite/React/Tailwind 前端。

---

## 项目结构

```
course_selection/
├── gpa_ranker.py             # Madgrades 客户端：find_course_uuid / compute_average_gpa / get_gpa
├── course_search.py          # enroll.wisc.edu 搜索客户端 + SearchFilters
├── search_with_gpa.py        # 桥接：enrich_hits_with_gpa / rank_hits_by_gpa / search_ranked_by_gpa
├── main.py                   # GPA Ranker CLI 入口（读 course_list.json）
├── course_list.json          # 输入：待排序课程清单
├── average_gpa_ranks.json    # 输出：按 GPA 排序的课程
├── aggreate.json             # 选课平台 aggregate 缓存（terms / subjects / sessions）
├── madgrades_openapi.json    # Madgrades API 规范（参考）
├── .gpa_cache.json           # GPA 结果持久化缓存（自动生成，已 gitignore）
├── .env                      # MADGRADES_API_TOKEN
├── requirements.txt
├── api/
│   └── server.py             # FastAPI：/api/terms, /api/subjects/{term}, /api/search
└── web/
    ├── package.json
    ├── vite.config.ts        # 代理 /api → http://localhost:8000
    └── src/
        ├── App.tsx
        ├── api.ts
        ├── types.ts
        └── components/{FilterPanel,ResultList,NoDataPanel}.tsx
```

---

## 快速开始

### 1. 安装依赖

```bash
# Python
pip install -r requirements.txt

# 前端
cd web && npm install && cd ..
```

### 2. 配置 Madgrades token

```bash
cp .env_example .env
# 编辑 .env，填入 MADGRADES_API_TOKEN=你的token
```

在 [api.madgrades.com](https://api.madgrades.com/) 注册免费获取。

### 3. 启动 Web 应用（两个终端）

```bash
# 终端 1 — 后端 (port 8000)
uvicorn api.server:app --reload --port 8000

# 终端 2 — 前端 (port 5173)
cd web && npm run dev
```

浏览器打开 http://localhost:5173，选 term / 填关键词 / 勾筛选器，点搜索。
结果会按 GPA 降序显示；没有 Madgrades 数据的课程显示在顶部的折叠 warning 面板里，
勾选"Hide courses without Madgrades GPA data"可隐藏（对应后端 `ignore_null=True`）。

---

## 三种使用方式

### A. Web UI

上面的流程。最适合探索式选课。

### B. Python 库 — 搜索 + 排序

```python
from course_search import CourseSearchClient, SearchFilters
from search_with_gpa import search_ranked_by_gpa
from gpa_ranker import save_gpa_cache

client = CourseSearchClient()
result = search_ranked_by_gpa(
    client,
    term="1264",
    keywords="calculus",
    advanced=True,
    ignore_null=False,      # True 时彻底丢弃无 GPA 的课程
    paginate_all=False,     # True 时翻完所有页（默认单页 50 条）
)

print(f"{result['found']} matched, {len(result['ranked'])} ranked")
for w in result["warnings"]:
    print(f"  warning: {w}")

for hit in result["ranked"][:10]:
    short = hit["subject"]["shortDescription"]
    print(f"  {short} {hit['catalogNumber']}: GPA={hit['gpa']:.2f} — {hit['title']}")

for hit in result["no_data"]:
    short = hit["subject"]["shortDescription"]
    print(f"  [no madgrades data] {short} {hit['catalogNumber']}: {hit['title']}")

save_gpa_cache()  # 持久化本次查到的 GPA 结果
```

返回结构：

```python
{
    "ranked":   [...],   # 有 GPA 的 hit，已按 gpa 降序排
    "no_data":  [...],   # 无 GPA 的 hit（ignore_null=True 时为空）
    "warnings": [...],   # 人类可读的提示
    "total":    int,     # 本次处理的 hit 数
    "found":    int,     # 服务端匹配总数
}
```

### C. Python 库 — 批量文件排序（原 GPA Ranker 流程）

输入 `course_list.json`：

```json
[
  {"catalog_number": "SOC 343", "course_title": "Sociology of Health"},
  {"catalog_number": "ECON 101", "course_title": "Microeconomics"}
]
```

```bash
python main.py
# → average_gpa_ranks.json（按 GPA 降序，无数据的课追加到末尾）
```

---

## API 端点

### 后端 (FastAPI, localhost:8000)

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/terms` | `{termCode: longDescription}` |
| GET | `/api/subjects/{termCode}` | `{subjectCode: formalDescription}` |
| POST | `/api/search` | 搜索 + GPA 排序。Body: `{filters, ignoreNull, paginateAll, maxPages}` |

### 上游

| API | Docs |
| --- | --- |
| enroll.wisc.edu | 逆向自前端 JS。详见 `course_search.py` 文件头 |
| Madgrades | [api.madgrades.com](https://api.madgrades.com/) (OpenAPI in `madgrades_openapi.json`) |

---

## 实现细节

### GPA 计算

使用 Madgrades `cumulative` 累计字段，按 4.0 绩点加权平均：

| 成绩 | 绩点 |
| --- | --- |
| A | 4.0 |
| AB | 3.5 |
| B | 3.0 |
| BC | 2.5 |
| C | 2.0 |
| D | 1.0 |
| F | 0.0 |

S/U/CR/N/P/I/NW/NR 等非字母等级不计入平均。

### 缓存 + 限流

- `get_gpa(catalog_number)` 读写内存 + `.gpa_cache.json`，`refresh=True` 强制刷新。
- 所有 Madgrades HTTP 请求经过全局 `_rate_limit()`（10 req/s 上限），`ThreadPoolExecutor(max_workers=5)` 内也安全。
- 子任务并发默认 5 个 worker，可通过 `max_workers=` 调整。

### 为什么 null 不丢到末尾

无 Madgrades 数据不等于 GPA 低——可能是新课、改过课号、或录入滞后。
把它们单独归到 `no_data` 分桶 + 在 UI 上折叠显示，用户可以选择性地忽略或单独审阅。
`ignore_null=True` 提供一刀切隐藏。

---

## 开发

前端开发命令：

```bash
cd web
npm run dev        # 开发服务器（代理到 8000）
npm run build      # 产品构建 → web/dist
npm run preview    # 预览构建产物
```

`User-Agent` 必须保持浏览器形态，否则 enroll.wisc.edu 返回 403。
`CourseSearchClient.DEFAULT_HEADERS` 已带 Chrome UA；覆盖时请注意。
