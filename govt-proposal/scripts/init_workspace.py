#!/usr/bin/env python3
"""
작업 폴더를 만들거나, 이미 있으면 어디까지 진행됐는지 알려준다.

각 단계 산출물을 파일로 남기는 것이 이 스킬의 상태 관리 방식이다.
대화가 길어지거나 세션이 끊겨도 파일만 있으면 이어서 작업할 수 있다.

사용:
    python init_workspace.py "포항제철_스마트팩토리"
    python init_workspace.py .              # 현재 폴더 진행 상태만 확인
"""
import argparse
import os
import sys
import unicodedata

STAGES = [
    ("00_입력",        "dir",  "1단계 공고문·작성양식·기업정보·심사표 (지정공모는 RFP 포함)"),
    ("01_아이디어.md", "file", "3단계 셀프 인터뷰 — 과제명 + 핵심 키워드 3개"),
    ("02_이해.md",     "file", "4단계 #이해 — 양식 지침 + 숨은 의도 + 입증 방안"),
    ("03_구조화.md",   "file", "5단계 #구조화 — 2차원 전략 매트릭스"),
    ("04_정렬.md",     "file", "6단계 #정렬 — 흐름 분석 열 + 키워드 정합성 행, 수정 반영"),
    ("05_본문",        "dir",  "7단계 섹션별 본문 (파일명은 양식 목차 기준)"),
    ("06_최종.md",     "file", "8단계 전달물 — 전략 검토 + 본문 + 준비할 입증 자료. 사업계획서실무교재.html로 열기"),
]


INPUT_README = """# 00_입력

여기에 다음 자료를 넣어 주세요.

| 파일 | 없으면 |
|---|---|
| 공고문 | 키워드 발굴의 근거가 사라집니다. 가장 아쉬운 누락입니다 |
| 작성양식(목차) | 일반 양식으로 추정해 진행합니다 |
| 기업정보 | 입증 전략이 전부 '제안' 수준에 머뭅니다 |
| 심사표 | 최종 검토에서 배점 대조를 못 합니다 |

한글 파일은 **.hwpx**로 저장해 주세요. XML 기반이라 정확히 읽힙니다.
구형 .hwp(바이너리)는 추출이 불안정합니다.

추출:
    python scripts/extract_doc.py 00_입력/공고문.hwpx -o 00_입력/공고문.md
"""


def norm_path(path):
    if os.path.exists(path):
        return path
    d = os.path.dirname(path) or "."
    base = unicodedata.normalize("NFC", os.path.basename(path))
    if os.path.isdir(d):
        for f in os.listdir(d):
            if unicodedata.normalize("NFC", f) == base:
                return os.path.join(d, f)
    return path


def has_content(path):
    """파일이 존재하고 실질 내용이 있는지."""
    if not os.path.exists(path):
        return False
    if os.path.isdir(path):
        return any(
            f for f in os.listdir(path)
            if not f.startswith(".") and f.lower() != "readme.md"
        )
    try:
        return len(open(path, encoding="utf-8").read().strip()) > 30
    except Exception:
        return os.path.getsize(path) > 0


def main():
    ap = argparse.ArgumentParser(description="작업 폴더 생성 / 진행 상태 확인")
    ap.add_argument("workspace", help="작업 폴더 경로")
    ap.add_argument("--no-create", action="store_true",
                    help="생성하지 않고 상태만 확인")
    args = ap.parse_args()

    ws = norm_path(args.workspace)
    existed = os.path.isdir(ws)

    if not existed:
        if args.no_create:
            sys.exit(f"폴더가 없습니다: {args.workspace}")
        os.makedirs(ws)

    # 스캐폴딩
    if not args.no_create:
        for name, kind, _ in STAGES:
            p = os.path.join(ws, name)
            if kind == "dir":
                os.makedirs(p, exist_ok=True)
        rd = os.path.join(ws, "00_입력", "README.md")
        if not os.path.exists(rd):
            with open(rd, "w", encoding="utf-8") as f:
                f.write(INPUT_README)

    # 상태 표시
    print(f"\n작업 폴더: {os.path.abspath(ws)}")
    print(f"상태: {'기존 폴더 — 이어서 진행' if existed else '새로 생성'}\n")

    print(f"{'단계':<16} {'상태':<6} 설명")
    print("-" * 72)

    next_stage = None
    for name, kind, desc in STAGES:
        p = os.path.join(ws, name)
        done = has_content(p)
        mark = "✅" if done else "⬜"
        if not done and next_stage is None:
            next_stage = (name, desc)
        print(f"{name:<16} {mark:<6} {desc}")

        if name == "05_본문" and os.path.isdir(p):
            # 본문 파일명은 양식 목차를 따르므로 고정 목록 없이 실제 파일을 보여준다
            for b in sorted(f for f in os.listdir(p) if f.endswith(".md")):
                bp = os.path.join(p, b)
                bm = "✅" if has_content(bp) else "⬜"
                print(f"  └ {b:<28} {bm}")

    print("-" * 72)
    if next_stage:
        print(f"\n→ 다음 단계: {next_stage[0]}  ({next_stage[1]})")
    else:
        print("\n→ 모든 단계 완료. 최종 검토와 전달만 남았습니다.")

    # 입력 자료 점검
    indir = os.path.join(ws, "00_입력")
    if os.path.isdir(indir):
        files = [f for f in os.listdir(indir)
                 if not f.startswith(".") and f.lower() != "readme.md"]
        if files:
            print(f"\n입력 자료 {len(files)}건: {', '.join(sorted(files))}")
            hwp = [f for f in files if f.lower().endswith(".hwp")]
            if hwp:
                print(f"  ⚠️  구형 .hwp 파일이 있습니다: {', '.join(hwp)}")
                print("     한글에서 HWPX로 다시 저장하면 정확히 읽힙니다.")
        else:
            print("\n⚠️  입력 자료가 비어 있습니다. 00_입력/README.md를 참고하세요.")


if __name__ == "__main__":
    main()
