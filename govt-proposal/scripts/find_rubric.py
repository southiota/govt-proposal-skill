#!/usr/bin/env python3
"""공고문에서 심사표(배점표)를 찾는다.

    python3 scripts/find_rubric.py <공고문.md> [--all]

심사표는 별도 파일로 오기도 하지만 **공고문 본문에 표로 들어 있는 경우가 더 많다**.
별도 파일이 없다고 기본 배점으로 넘어가면 실제 배점을 놓친다.

추출본(`extract_doc.py --tables`)을 넣는다. 표를 훑어 배점표 후보를 점수순으로 보여준다.
`--all` 을 주면 후보를 전부, 없으면 가장 확실한 하나만.
"""
import argparse
import re
import sys
from pathlib import Path

HEAD_HINT = re.compile(r"배점|점수|가중치|비중|평가\s*항목|심사\s*항목")
CTX_HINT = re.compile(r"평가\s*기준|평가\s*항목|심사\s*기준|심사\s*항목|배점|가점")
SCORE = re.compile(r"^\s*\(?\d{1,3}(\.\d)?\s*(점|%)?\s*\)?$")
SUM_ROW = re.compile(r"^\s*(합\s*계|총\s*계|계|소\s*계)\s*$")


def cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def tables(lines):
    """(시작줄, 앞 문맥, 행들) 목록."""
    out, i = [], 0
    while i < len(lines):
        if lines[i].strip().startswith("|"):
            j = i
            while j < len(lines) and lines[j].strip().startswith("|"):
                j += 1
            ctx = " ".join(l.strip() for l in lines[max(0, i - 6):i] if l.strip())
            out.append((i + 1, ctx, lines[i:j]))
            i = j
        else:
            i += 1
    return out


def score_table(ctx, rows):
    """배점표다움을 점수로. 근거도 함께 돌려준다."""
    if len(rows) < 3:
        return 0, []
    hd = cells(rows[0])
    why, pts = [], 0
    if any(HEAD_HINT.search(h) for h in hd):
        pts += 3; why.append("머리에 배점·평가 항목")
    if CTX_HINT.search(ctx):
        pts += 2; why.append("앞 문맥이 평가 기준")
    body = [cells(r) for r in rows[1:]]
    numcol = 0
    for col in range(1, max((len(r) for r in body), default=1)):
        vals = [r[col] for r in body if len(r) > col and r[col]]
        if vals and sum(1 for v in vals if SCORE.match(v)) >= max(2, len(vals) * 0.6):
            numcol += 1
    if numcol:
        pts += 3; why.append(f"점수 열 {numcol}개")
    if any(SUM_ROW.match(r[0]) for r in body if r):
        pts += 2; why.append("합계 행")
    total = 0
    for r in body:
        for v in r:
            m = re.match(r"^\s*(\d{1,3})\s*점?\s*$", v)
            if m and SUM_ROW.match(r[0] if r else ""):
                total = max(total, int(m.group(1)))
    if total in (100, 50):
        pts += 2; why.append(f"합계 {total}")
    return pts, why


def main():
    ap = argparse.ArgumentParser(description="공고문에서 심사표 찾기")
    ap.add_argument("path", help="extract_doc.py --tables 로 뽑은 md")
    ap.add_argument("--all", action="store_true", help="후보를 전부 보여준다")
    ap.add_argument("--min", type=int, default=5, help="후보로 볼 최소 점수 (기본 5)")
    args = ap.parse_args()

    lines = Path(args.path).read_text(encoding="utf-8", errors="replace").split("\n")
    cands = []
    for at, ctx, rows in tables(lines):
        pts, why = score_table(ctx, rows)
        if pts >= args.min:
            cands.append((pts, at, ctx, rows, why))
    cands.sort(key=lambda x: -x[0])

    if not cands:
        print("심사표를 찾지 못했습니다.")
        print("  → 공고문에 배점표가 없을 수 있습니다. 별도 심사표 파일을 확인하고,")
        print("     그것도 없으면 `[기본값]` 배점표로 대조합니다 (최종산출물_포맷.md 3.10).")
        return 1

    for k, (pts, at, ctx, rows, why) in enumerate(cands if args.all else cands[:1]):
        print(f"\n{'='*66}\n  심사표 후보 {k+1} — L{at} · 확신도 {pts}점 ({', '.join(why)})\n{'='*66}")
        if ctx:
            print(f"  앞 문맥: {ctx[:90]}")
        print()
        for r in rows:
            print("  " + r.strip())
    if len(cands) > 1 and not args.all:
        print(f"\n  후보 {len(cands)}개 중 1개만 보였습니다. 전부 보려면 --all")
    print("\n  ※ 이 배점을 `# 심사표 대조` 에 그대로 쓰고 항목별 강·약을 채웁니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
