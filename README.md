# Course Selection GPA Ranker

一个通过 [Madgrades API](https://api.madgrades.com/v1) 按平均 GPA 从高到低
排序 UW–Madison 课程的小工具。读取 `course_list.json`，查询每门课的历史成绩
分布，计算加权平均 GPA，并把排序结果写入 `average_gpa_ranks.json`。

## 项目结构

```
course_selection/
├── course_list.json          # 输入：待排序的课程列表
├── madgrades_openapi.json    # Madgrades API 的 OpenAPI 规范（参考）
├── gpa_ranker.py             # 通用排序与保存函数
├── main.py                   # 程序入口
├── .env_example              # 环境变量模板
└── README.md
```

## 安装

需要 Python 3.8+。

```bash
pip install requests python-dotenv
```

## 配置

1. 在 [Madgrades](https://api.madgrades.com/) 注册并获取你的 API token。
2. 复制环境变量模板并填入 token：

   ```bash
   cp .env_example .env
   ```

   然后编辑 `.env`：

   ```
   MADGRADES_API_TOKEN=你的token
   ```

## 输入格式

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

## 运行

```bash
python main.py
```

程序会依次查询每门课的 GPA，并在当前目录生成 `average_gpa_ranks.json`，
内容是按平均 GPA 从高到低排序的对象数组，每个元素格式为：

```json
[
  {
    "catalog_number": "SOC 343",
    "course_title": "Sociology of Health and Medicine",
    "gpa": 3.8474
  },
  {
    "catalog_number": "ECON 101",
    "course_title": "Principles of Microeconomics",
    "gpa": 3.0548
  },
  {
    "catalog_number": "SOME 999",
    "course_title": "Course Not in Madgrades",
    "gpa": null
  }
]
```

`gpa` 为 `null` 的情况有两种：该课程在 Madgrades 系统中不存在，或系统中
存在但尚无历史成绩数据。这两种情况下该课程会追加在列表末尾。

## 作为模块调用

`gpa_ranker.py` 暴露两个通用函数，可在其他脚本中复用：

```python
from gpa_ranker import rank_courses_by_gpa, save_ranked_courses

ranked = rank_courses_by_gpa("course_list.json")   # 也支持绝对路径
save_ranked_courses(ranked, "average_gpa_ranks.json")
```

- `rank_courses_by_gpa(path)` — 接收 `course_list.json` 格式文件的路径
  （相对或绝对），返回按 GPA 从高到低排序的 dict 列表，每个 dict 包含
  `catalog_number`、`course_title`、`gpa`（无数据时为 `None`）。
- `save_ranked_courses(ranked, output_name)` — 把上述列表以 JSON 格式写到
  指定文件名，返回写入文件的绝对路径。

## GPA 计算方式

对每门课调用 `/courses/{id}/grades`，使用响应顶层的 `cumulative` 累计
字段（涵盖全部学期所有 section），按标准 4.0 绩点计算加权平均：

| 成绩 | 绩点 |
| --- | --- |
| A   | 4.0 |
| AB  | 3.5 |
| B   | 3.0 |
| BC  | 2.5 |
| C   | 2.0 |
| D   | 1.0 |
| F   | 0.0 |

S/U/CR/N/P/I/NW/NR/other 等非字母等级不计入平均。
