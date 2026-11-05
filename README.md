# uav-inspector

反无人机设备巡检记录 → 结构化运维报告 自动生成器。

输入现场巡检日志（射频侦测 / 雷达+视觉 / 无线电压制 / 激光 四类设备），
输出带风险分级、故障归因和处置动作的 Markdown 运维报告。

[![CI](https://github.com/Gabbie01/uav-inspector/actions/workflows/ci.yml/badge.svg)](https://github.com/Gabbie01/uav-inspector/actions/workflows/ci.yml)
[![Python 3.11](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![ruff](https://img.shields.io/badge/ruff-clean-green.svg)](https://docs.astral.sh/ruff/)
[![mypy](https://img.shields.io/badge/mypy-strict-green.svg)](https://mypy-lang.org/)
[![pytest](https://img.shields.io/badge/pytest-offline%20%2B%20coverage%20gate-green.svg)](https://docs.pytest.org/)
[![license](https://img.shields.io/badge/license-MIT-lightgrey.svg)](LICENSE)

---

## 一分钟看懂这个项目

| 你关心的 | 答案 | 怎么验证 |
|---|---|---|
| 真的能跑吗？ | 3 份现场日志 → 3 份完整运维报告，全部入库 | [`docs/examples/`](docs/examples/) |
| 模型会编数据怎么办？ | 代码层事实校验闸门，逐条回查原始日志 | [`scripts/hallucination_demo.py`](scripts/hallucination_demo.py) |
| 报告里的证据是真的吗？ | 拿原始日志当唯一真相独立校验 | [`scripts/verify_examples.py`](scripts/verify_examples.py) |
| 质量有人把关吗？ | GitHub Actions 全绿，ruff + mypy strict + pytest | [CI 徽章](https://github.com/Gabbie01/uav-inspector/actions/workflows/ci.yml) |
| 不联网能复现吗？ | 零密钥、零费用、可离线跑通全流程 | `make demo` |

三条命令，本机就能全部验证：

```bash
make demo               # 离线跑通：解析 → 模型 → 校验 → 渲染（不需要 API Key）
make demo-hallucination # 看闸门如何拦下四类模型幻觉（不需要 API Key）
make verify-examples    # 逐条回查三份真实报告的证据行（不需要 API Key）
```

---

## 真实产出样例

下面三份报告是**用真实大模型跑出来的完整产出**（不是手写示例、不是模板填充），
已入库在 [`docs/examples/`](docs/examples/)，并由 CI 每次自动校验。

| 报告 | 现场 | 日志 | 整体状态 | 说明 |
|---|---|---|---|---|
| [`report_2026-10-28.md`](docs/examples/report_2026-10-28.md) | 深圳-临港低空防护示范点A | 51 行 / 4 台设备 | 严重 | 四类设备全覆盖，含压制设备过温降功率与光电转台复位失败 |
| [`report_2026-10-29-b.md`](docs/examples/report_2026-10-29-b.md) | 深圳-机场货运区防护点B | 37 行 / 4 台设备 | 中等 | 射频侦测双机（RF-DET-01/02）同场，含疑似图传信号压制处置 |
| [`report_2026-10-30-c.md`](docs/examples/report_2026-10-30-c.md) | 深圳-跨海大桥监测哨点C | 36 行 / 3 台设备 | 中等 | 含 2 行格式异常日志，正确计入「未解析 2 行」统计 |

报告节选（真实产出，完整版见链接）：

```markdown
# 反无人机设备巡检报告

- **现场**：深圳-跨海大桥监测哨点C
- **整体状态**：[中等] 中等
- **日志统计**：共 36 行，可解析 34 行，未解析 2 行，覆盖 3 台设备，其中 2 台存在问题
- **问题分级**：中等 2（最高 中等）

## 二、问题明细

### 2. [中等] 雷达高温降功率并出现回波异常（RD-EO-02）

- **设备类型**：雷达+视觉设备
- **风险等级**：中等
- **现象与判断**：09:17雷达前端放大器温度达到74C并进入降功率模式，随后量程由2km降至1.2km；
  10:06温度回落至51C并恢复正常量程。另有无法解析行记录14:02雷达回波异常，峰值为-48dBm，
  随后14:05光电系统切换至手动模式。
- **原始记录**：

  ```text
  2026-10-30 09:17:04 [RD-EO-02] ERROR  雷达前端放大器温度 74C 超阈值，雷达进入降功率工作模式
  2026-10-30 09:19:41 [RD-EO-02] WARN  雷达量程由 2km 降至 1.2km，探测能力下降
  2026-10-30 10:06:13 [RD-EO-02] INFO  雷达前端温度回落至 51C，恢复正常量程
  ```
```

注意最后那段 `原始记录`：**每一行都能在 `data/samples/inspection_2026-10-30-c.log` 里逐字找到**。
这一点不是靠承诺，是靠 CI 每次自动校验：

```console
$ make verify-examples
========================================================================
uav-inspector · 真实报告事实校验（离线，不调用任何 API）
========================================================================
报告目录   : docs/examples

[PASS] report_2026-10-28.md
       证据行、设备编号、分级统计、头部统计全部与原始日志一致
[PASS] report_2026-10-29-b.md
       证据行、设备编号、分级统计、头部统计全部与原始日志一致
[PASS] report_2026-10-30-c.md
       证据行、设备编号、分级统计、头部统计全部与原始日志一致

结果：3 份真实报告全部通过事实校验。
========================================================================
```

---

## 为什么做这个项目

这不是一个「调用一下大模型 API」的玩具。它复刻的是低空安全/反无人机行业里
真实存在、但很少有人用工程化方式做掉的一环：**现场巡检数据的结构化与报告自动化**。

设计上的三条硬规矩（也是面试时最值得讲的三点）：

1. **确定性的部分用代码，判断力的部分才用模型。**
   日志解析、设备类型推断、风险统计、证据校验全部在代码里完成。
   模型只负责它真正擅长的：跨记录归因、风险定级、处置建议。

2. **模型输出必须过 schema 校验，校验失败让模型自己修。**
   不是把模型返回的字符串直接塞进报告，而是 Pydantic 强校验 + 修复重试。

3. **事实校验闸门：模型不许编造。**
   模型可能虚构设备编号或伪造证据行。代码会逐条比对日志，
   剔除虚构设备、把对不上的证据替换成真实日志行，并在报告里标注数据质量问题。

### 第 3 条长什么样（可复现演示）

`make demo-hallucination` 会人为给模型注入四类幻觉，然后展示闸门怎么拦：

```console
$ make demo-hallucination
------------------------------------------------------------------------
① 模型原始输出（人为注入幻觉）
------------------------------------------------------------------------
整体状态   : 紧急
  · RF-DET-99    [射频信号侦测设备] 紧急 — 射频侦测设备 RF-DET-99 完全离线
      ✗ 2026-10-30 08:50:00 [RF-DET-99] ERROR  设备离线，功放模块烧毁
  · LASER-01     [激光设备] 严重 — 激光测距模块自检失败
        2026-10-30 08:50:26 [LASER-01] ERROR  激光测距模块自检失败，返回码 E-104，测距无输出
      ✗ 2026-10-30 08:51:03 [LASER-01] ERROR  激光发射管温度 480C 超阈值，已损坏
  · RD-EO-02     [雷达+视觉设备] 严重 — 雷达前端放大器损坏
      ✗ 2026-10-30 11:00:00 [RD-EO-02] ERROR  雷达前端放大器硬件损坏，量程降至 0.3km
  · RD-EO-01     [激光设备] 中等 — 雷达探测到慢速回波，高度 480m
        2026-10-30 08:04:52 [RD-EO-01] WARN  500m 高度层检测到慢速回波，高度 480m 方位 32 度，疑似民用旋翼

  ✗ = 这条证据在原始日志里根本不存在

------------------------------------------------------------------------
② 事实校验闸门处理结果
------------------------------------------------------------------------
剔除问题项 1 条 / 保留 3 条，拦截说明 2 条：
  · RF-DET-99：日志中不存在该设备，疑似模型虚构，已剔除
  · RD-EO-02：模型给出的证据无法在日志中匹配，已替换为该设备的真实日志行

------------------------------------------------------------------------
④ 客观统计与整体状态（全部由代码重算，不采信模型给的数字）
------------------------------------------------------------------------
模型声称整体状态 : 紧急
代码重算整体状态 : 严重

------------------------------------------------------------------------
⑤ 闸门自检
------------------------------------------------------------------------
  [PASS] 虚构设备 RF-DET-99 被剔除
  [PASS] 伪造证据行被剔除
  [PASS] 伪造的雷达证据被剔除
  [PASS] 真实证据行被逐条保留（没被整份替换掉）
  [PASS] 所有留存证据都能在原始日志中逐字匹配
  [PASS] RD-EO-01 的设备类型被纠正回真实值
  [PASS] RD-EO-02 的编造证据被替换为真实日志行
  [PASS] 整体状态按清洗后问题项重算，未沿用模型虚高值
  [PASS] 严重度统计由代码重算，与清洗后问题项一致

结果：全部自检通过 —— 模型幻觉被完整拦截，报告只保留可追溯的事实。
```

四类幻觉分别被这样处理：

| 幻觉类型 | 注入的例子 | 闸门怎么处理 |
|---|---|---|
| 虚构设备编号 | `RF-DET-99` 根本不在日志里 | 整个问题项剔除，并在报告标注数据质量说明 |
| 伪造证据行 | 看着像日志，原文里没有 | 逐条丢弃该行，保留同项下的真实行 |
| 设备类型张冠李戴 | 把雷达+视觉设备写成激光设备 | 按日志推断的设备类型纠正回来 |
| 整体状态虚高 | 靠虚构设备撑出来的「紧急」 | 按清洗后的问题项重算，不采信模型给的数字 |

这个演示脚本已纳入 CI：**闸门一旦失守，CI 直接变红**，而不是靠人记得去看。

---

## 快速开始

```bash
cd ~/projects/uav-inspector

# 1. 装依赖（uv 会自动建 .venv）
make install

# 2. 离线演示：完整跑通解析 -> 模型 -> 校验 -> 渲染，不需要 API Key
make demo

# 3. 配置真实模型
cp .env.example .env
# 编辑 .env，填入 LLM_API_KEY

# 4. 自检：检查配置和 API 连通性
make doctor

# 5. 用真实模型生成报告
make generate
```

输出默认打印到屏幕，也可以写文件：

```bash
uv run uav-inspect generate data/samples/inspection_2026-10-28.log \
    --site "深圳-某低空防护示范点" \
    --output reports/2026-10-28.md
```

### 全部可用命令

| 命令 | 作用 | 需要 API Key |
|---|---|---|
| `make install` | 初始化虚拟环境并安装依赖 | 否 |
| `make test` | 跑单元测试 + 覆盖率门槛 | 否 |
| `make lint` | ruff 静态检查（`src tests scripts`） | 否 |
| `make fmt` | ruff 自动格式化 | 否 |
| `make typecheck` | mypy 严格模式 | 否 |
| `make demo` | 离线演示：解析样例日志并生成报告 | 否 |
| `make demo-hallucination` | 幻觉闸门演示：注入假幻觉，看代码如何拦截 | 否 |
| `make verify-examples` | 真实报告样例事实校验：逐条回查 `docs/examples/` | 否 |
| `make doctor` | 环境自检：配置与 API 连通性 | 是 |
| `make generate` | 用真实大模型生成报告 | 是 |

---

## 架构

```
data/samples/inspection_*.log
        │
        ▼
   parser.py        正则解析 + 关键词先验定级  ──→  LogRecord[]
        │                                        (纯确定性)
        ▼
   prompts.py       组装角色设定 + 结构化上下文 + 输出 schema
        │
        ▼
   llm.py           OpenAI 兼容客户端
        │             ├─ 重试 + 指数退避（限流/超时/5xx）
        │             ├─ json_object 约束输出
        │             └─ Pydantic 校验失败 → 回灌错误让模型重写
        │
        ▼
   report.py        ★ 事实校验闸门
        │             ├─ 剔除模型虚构的设备编号
        │             ├─ 证据行必须能在日志中匹配，否则替换为真实行
        │             └─ 合并代码计算的客观统计（不采信模型给的数字）
        │
        ▼
   render.py        Markdown / 纯文本渲染
        │
        ▼
   InspectionReport
```

模块职责：

| 模块 | 职责 | 是否依赖模型 |
|---|---|---|
| `config.py` | 环境变量/`.env` 配置，`SecretStr` 保护密钥 | 否 |
| `models.py` | Pydantic 数据模型 + 风险等级 + 设备类型 | 否 |
| `parser.py` | 日志解析、设备类型推断、关键词先验定级 | 否 |
| `prompts.py` | 提示词模板、修复提示词 | — |
| `llm.py` | 客户端、重试、结构化输出、校验修复、离线 FakeLLM | 是 |
| `report.py` | 编排 + 事实校验 + 统计合并 | 部分 |
| `render.py` | Markdown / 纯文本渲染 | 否 |
| `cli.py` | `generate` / `demo` / `doctor` | 部分 |

---

## 支持的模型服务

全部走 OpenAI 兼容协议，改 `.env` 里的 `LLM_BASE_URL` 和 `LLM_MODEL` 即可切换：

| 服务 | base_url | 备注 |
|---|---|---|
| DeepSeek | `https://api.deepseek.com/v1` | 性价比最高，适合练手 |
| Moonshot | `https://api.moonshot.cn/v1` | 长文本 |
| 阿里百炼 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 通义千问 |
| SiliconFlow | `https://api.siliconflow.cn/v1` | 模型多 |
| OpenAI | `https://api.openai.com/v1` | 官方 |

---

## 测试与质量闸门

```bash
make test        # 单元测试，完全不联网
make lint        # ruff
make typecheck   # mypy 严格模式
```

当前状态：**154 个用例（153 通过 / 1 跳过），覆盖率 93.52%，ruff / mypy strict 全绿。**

CI 流水线（[`.github/workflows/ci.yml`](.github/workflows/ci.yml)）在 Python 3.11 / 3.12 双版本上跑，
全程离线、不需要任何密钥、不产生 API 费用：

| 步骤 | 作用 |
|---|---|
| `uv sync --locked` | 严格按锁文件安装，保证 CI 装的依赖与本地提交完全一致 |
| `ruff check src tests scripts` | 静态检查，脚本目录也纳入 |
| `make -n help / test / lint / demo-hallucination / verify-examples` | 校验 README 里写的 make 命令真的能用 |
| `mypy` | 严格类型检查 |
| `pytest` | 单测 + 覆盖率门槛 70% |
| `scripts/hallucination_demo.py` | 幻觉闸门自检，9 项断言，失守即红 |
| `scripts/verify_examples.py` | 三份真实报告的事实校验，失守即红 |
| 密钥检查 | 确认环境无 `.env`、无 `LLM_API_KEY`，且历史里从未提交过 `.env` |

测试用 `FakeLLM` 替换真实模型，因此 CI 里不需要任何密钥，也不会产生 API 费用。

---

## 目录结构

```
src/uav_inspector/     包源码
tests/                 pytest 用例
scripts/               可复现演示与校验脚本（纳入 ruff 与 CI）
data/samples/          样例巡检日志（虚构数据）
docs/examples/         三份真实大模型产出的报告样例
reports/               本地生成结果（git 忽略）
.env.example           配置模板
Makefile               常用命令快捷方式
```

---

## 后续规划

- [ ] 接入 `dvc` 做数据版本管理，巡检记录可追溯
- [ ] 报告导出 PDF / 微信企业格式
- [ ] 按设备维度做历史趋势对比，识别慢性劣化
- [ ] 接入向量检索：把历史工单作为 few-shot 样例喂给模型
- [ ] 视觉侧扩展：无人机小目标检测（YOLO + TensorRT 边缘部署）

---

## 说明

本项目为个人作品集项目，用于展示 LLM 应用工程化能力。
日志样例为虚构数据，不涉及任何真实客户、涉密项目或厂商产品。
`docs/examples/` 下的报告由真实大模型基于虚构日志生成，其中的每一条证据行
均可回查至仓库内的样例日志原文。
