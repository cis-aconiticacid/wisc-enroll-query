# UW-Madison Course Selection Toolkit

UW-Madison 选课工具集，包含两个模块：

1. **GPA Ranker** — 通过 [Madgrades API](https://api.madgrades.com/v1) 查询
   历史成绩分布，按平均 GPA 从高到低排序课程。
2. **Course Search Client** — 逆向自 [public.enroll.wisc.edu](https://public.enroll.wisc.edu)
   前端的选课搜索客户端，支持搜索、筛选、获取课程详情和 enrollment packages。
   通过伪装浏览器 `User-Agent` header 访问（服务器仅校验 UA）。

## 项目结构

```
course_selection/
├── course_list.json          # 输入：待排序的课程列表
├── madgrades_openapi.json    # Madgrades API 的 OpenAPI 规范（参考）
├── gpa_ranker.py             # GPA 排序与保存函数
├── main.py                   # GPA Ranker 程序入口
├── .env_example              # 环境变量模板（Madgrades token）
├── course_search.py          # UW-Madison 选课搜索 API 客户端
├── aggreate.json             # 选课平台 aggregate 接口的本地缓存（编码参考表）
└── README.md
```

---

## Course Search Client

### 快速开始

```python
from course_search import CourseSearchClient, SearchFilters

client = CourseSearchClient()

# 基础搜索
result = client.search(term="1264", keywords="calculus")
print(f"Found {result['found']} courses")
for hit in result["hits"]:
    subj = hit["subject"]["shortDescription"]
    print(f"  {subj} {hit['catalogNumber']}: {hit['title']}")
```

### 自定义 Headers

默认已带浏览器 UA，直接能用。如需覆盖或添加 header：

```python
client = CourseSearchClient(headers={"Cookie": "session=abc123"})
```

> **注意**：服务器校验 `User-Agent`，如果覆盖为非浏览器 UA 会返回 403。

### 筛选搜索

```python
filters = SearchFilters(
    term="1264",
    keywords="analysis",
    advanced=True,             # 仅高级课程
    open=True,                 # 仅有空位的课程
    modeOfInstruction="classroom",
)
result = client.search(filters)
```

### 获取课程详情 / Sections

```python
hit = result["hits"][0]
details = client.get_details_for_hit(hit)     # 课程详情
packages = client.get_packages_for_hit(hit)   # enrollment packages / sections
```

### 本地编码参考表

`aggreate.json` 在模块加载时自动读取，提供以下查找表（可直接 import）：

```python
from course_search import KNOWN_TERMS, SESSIONS_BY_TERM, SUBJECTS_BY_TERM

KNOWN_TERMS        # {"1264": "Spring 2025-2026", ...}
SESSIONS_BY_TERM   # {"1264": [session_dict, ...], ...}
SUBJECTS_BY_TERM   # {"1264": {"416": "GEOGRAPHY", ...}, ...}
```

### API Endpoints

| Method | Endpoint | Description |
| --- | --- | --- |
| POST | `/api/search/v1` | 课程搜索 |
| GET | `/api/search/v1/aggregate` | terms / sessions / subjects / specialGroups |
| GET | `/api/search/v1/subjectsMap/{termCode}` | 某学期的 subject 列表 |
| GET | `/api/search/v1/details/{termCode}/{subjectCode}/{courseId}` | 课程详情 |
| GET | `/api/search/v1/enrollmentPackages/{termCode}/{subjectCode}/{courseId}` | sections |

> `subjectCode` 是数字编码（如 `"600"` = MATH），不是字母缩写。

---

## GPA Ranker

### 配置

1. 在 [Madgrades](https://api.madgrades.com/) 注册并获取 API token。
2. 复制环境变量模板并填入 token：

   ```bash
   cp .env_example .env
   ```

   编辑 `.env`：

   ```
   MADGRADES_API_TOKEN=你的token
   ```

### 输入格式

`course_list.json` 是一个数组，每个元素至少包含 `catalog_number` 和
`course_title` 字段：

```json
[
  {
    "catalog_number": "SOC 343",
    "credits": "3.00 credits",
    "course_title": "Sociology of Health and Medicine"
  }
]
```

### 运行

```bash
pip install requests python-dotenv
python main.py
```

输出 `average_gpa_ranks.json`，按平均 GPA 从高到低排序：

```json
[
  {"catalog_number": "SOC 343", "course_title": "Sociology of Health and Medicine", "gpa": 3.8474},
  {"catalog_number": "ECON 101", "course_title": "Principles of Microeconomics", "gpa": 3.0548},
  {"catalog_number": "SOME 999", "course_title": "Course Not in Madgrades", "gpa": null}
]
```

`gpa` 为 `null` 表示课程在 Madgrades 中不存在或无历史成绩数据。

### 作为模块调用

```python
from gpa_ranker import rank_courses_by_gpa, save_ranked_courses

ranked = rank_courses_by_gpa("course_list.json")
save_ranked_courses(ranked, "average_gpa_ranks.json")
```

### GPA 计算方式

使用 Madgrades `cumulative` 累计字段，按标准 4.0 绩点加权平均：

| 成绩 | 绩点 |
| --- | --- |
| A | 4.0 |
| AB | 3.5 |
| B | 3.0 |
| BC | 2.5 |
| C | 2.0 |
| D | 1.0 |
| F | 0.0 |

S/U/CR/N/P/I/NW/NR/other 等非字母等级不计入平均。
