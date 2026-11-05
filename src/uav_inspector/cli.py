"""命令行入口。

子命令：
    generate  用真实大模型从日志生成报告
    demo      离线演示（不需要 API Key），完整跑通解析->模型->校验->渲染
    doctor    环境自检：配置、依赖、API 连通性
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import get_settings
from .llm import FakeLLM, LLMError, OpenAICompatibleClient
from .models import InspectionReport
from .parser import parse_log_file
from .render import render_markdown, render_plain
from .report import generate_report, severity_prior_table

logger = logging.getLogger("uav_inspector")


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def _write_output(report: InspectionReport, output: str | None, fmt: str) -> None:
    text = render_markdown(report) if fmt == "markdown" else render_plain(report)
    if output is None:
        print(text)
        return
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"报告已写入：{path}")


def cmd_generate(args: argparse.Namespace) -> int:
    settings = get_settings()
    if not settings.has_api_key:
        print(
            "[错误] 未配置 LLM_API_KEY。\n"
            "      cp .env.example .env  然后填入你的 key。\n"
            "      想先看效果请运行： uav-inspect demo",
            file=sys.stderr,
        )
        return 2

    try:
        client = OpenAICompatibleClient(settings)
    except LLMError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 2

    try:
        report = generate_report(client, Path(args.log).read_text(encoding="utf-8"), site=args.site)
    except LLMError as exc:
        print(f"[错误] 模型调用失败：{exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()

    _write_output(report, args.output, args.format)
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    settings = get_settings()
    _setup_logging(settings.log_level)

    log_path = Path(args.log)
    if not log_path.exists():
        print(f"[错误] 样例日志不存在：{log_path}", file=sys.stderr)
        return 1

    records, unparsed = parse_log_file(log_path)
    print(f"解析 {len(records)} 条记录，未解析 {len(unparsed)} 行")
    print("先验风险分布（代码计算，不经模型）：")
    for device_id, severity in severity_prior_table(records):
        print(f"  {device_id:<14} {severity.value}")
    print()

    client = FakeLLM()
    report = generate_report(client, log_path.read_text(encoding="utf-8"), site=args.site)

    print("[演示模式] 使用内置离线模型，未调用外部 API。真实运行请用 `uav-inspect generate`。")
    print("-" * 60)
    _write_output(report, args.output, args.format)
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    settings = get_settings()
    _setup_logging(settings.log_level)

    print("== uav-inspector 环境自检 ==")
    print(f"Python        : {sys.version.split()[0]}")
    print(f"base_url      : {settings.llm_base_url}")
    print(f"model         : {settings.llm_model}")
    print(f"timeout       : {settings.llm_timeout_s}s")
    print(f"max_retries   : {settings.llm_max_retries}")
    print(f"temperature   : {settings.llm_temperature}")
    print(f"API Key       : {'已配置' if settings.has_api_key else '未配置（.env）'}")

    sample = Path(__file__).resolve().parents[2] / "data" / "samples" / "inspection_2026-10-28.log"
    if sample.exists():
        records, unparsed = parse_log_file(sample)
        print(f"样例日志      : {len(records)} 条可解析，{len(unparsed)} 行未解析")

    if not settings.has_api_key:
        print("\n结果：未配置 API Key，离线 demo 仍可运行。")
        return 0

    try:
        client = OpenAICompatibleClient(settings)
    except LLMError as exc:
        print(f"\n结果：客户端初始化失败 -> {exc}")
        return 1

    try:
        reply = client.complete_json(
            "你是连通性测试助手。",
            '只输出 JSON：{"ok": true, "message": "连接正常"}',
        )
        print(f"\n结果：API 连通正常，模型返回 -> {reply.strip()[:200]}")
        return 0
    except LLMError as exc:
        print(f"\n结果：API 连通失败 -> {exc}")
        return 1
    finally:
        client.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uav-inspect",
        description="反无人机设备巡检记录 -> 结构化运维报告 自动生成器",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    default_sample = (
        Path(__file__).resolve().parents[2] / "data" / "samples" / "inspection_2026-10-28.log"
    )

    gen = sub.add_parser("generate", help="用真实大模型生成报告")
    gen.add_argument("log", help="巡检日志文件路径")
    gen.add_argument("--site", default="未指定现场", help="现场名称/编号")
    gen.add_argument("--output", "-o", default=None, help="输出文件路径（默认打印到屏幕）")
    gen.add_argument("--format", choices=["markdown", "text"], default="markdown", help="输出格式")
    gen.set_defaults(func=cmd_generate)

    demo = sub.add_parser("demo", help="离线演示，不需要 API Key")
    demo.add_argument("--log", default=str(default_sample), help="样例日志路径")
    demo.add_argument("--site", default="深圳-示例低空防护示范点", help="现场名称")
    demo.add_argument("--output", "-o", default=None, help="输出文件路径")
    demo.add_argument("--format", choices=["markdown", "text"], default="markdown", help="输出格式")
    demo.set_defaults(func=cmd_demo)

    doctor = sub.add_parser("doctor", help="环境自检")
    doctor.set_defaults(func=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(get_settings().log_level)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
