#!/usr/bin/env python3
"""
핵심 키워드 3개가 계획서 전반에 고르게 반복되는지 정량 검증한다.

"설득은 순서와 반복"이라는 원칙을 눈대중이 아니라 숫자로 확인하기 위한 도구다.
병렬 반복 — 배경1 → 필요성1 → 개발내용1이 같은 키워드로 이어지는 구조 — 이
지켜지고 있는지 섹션별 분포로 드러난다.

사용:
    python audit_keywords.py 05_본문/ --keywords 피지컬AI,휴먼에러,중대재해
    python audit_keywords.py 06_최종.md --keywords A,B,C
    python audit_keywords.py 04_정렬.md --auto      # #태그에서 키워드 자동 추출
"""
import argparse
import os
import re
import sys
import unicodedata
from collections import OrderedDict


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


def normalize(s):
    """공백·가운뎃점 제거 후 비교 (피지컬 AI == 피지컬AI)."""
    return re.sub(r"[\s·\-_]", "", s)


def auto_keywords(text, top=3):
    """#태그 또는 (#키워드) 패턴에서 키워드 추출."""
    cands = re.findall(r"\(#([^)]{1,20})\)", text) + re.findall(r"#([가-힣A-Za-z0-9]{2,20})", text)
    counts = OrderedDict()
    for c in cands:
        k = c.strip()
        counts[k] = counts.get(k, 0) + 1
    return [k for k, _ in sorted(counts.items(), key=lambda x: -x[1])[:top]]


# 병렬 반복 대상이 아닌 것: 06_최종의 고정 부분, 행정 항목(자가진단·안전보안·일반현황 등)
STRATEGY_RE = re.compile(r"^(전략\s*검토|확인할\s*규정|준비할\s*입증|심사표\s*대조|입증\s*자료|핵심\s*키워드|전략\s*매트릭스|유지할\s*점)")
# 매트릭스에서 제외하는 것과 같은 목록이어야 한다(04_구조화_유형별.md).
# 여기서 빼지 않으면 병합본에 돌렸을 때 행정 항목마다 '키워드 없음' 이 떠 노이즈가 된다.
ADMIN_RE = re.compile(
    r"자가\s*진단|안전|보안|일반\s*현황|윤리|서약|체크리스트|점검표|"
    r"연구원\s*현황|참여\s*인력|참여기관|인력\s*현황|"
    r"연구비|사업비|자금|예산|조달|"
    r"일정|추진\s*일정|기술개발\s*일정|"
    r"장비|시설|개인정보|동의서|사업자등록|신고필증|"
    r"특허,\s*논문|수상|첨부|붙임|별첨")


def split_sections(text, h1_only=False):
    """헤딩으로 섹션 분할. h3 이하(세부 개발 항목 등)는 상위 섹션에 포함한다.

    세부 항목 제목까지 섹션으로 쪼개면 '1-1. 멀티모달 파이프라인' 같은 줄마다
    키워드 누락이 뜨는데, 이는 의미 없는 노이즈다. 병렬 반복은 목차 단위로 본다.

    h1_only=True 는 `#` 대항목만 섹션으로 본다. **병합본(06_최종.md)에 쓴다** —
    매트릭스는 대항목 축이므로 소항목마다 키워드 3개를 요구하면 과하다.
    """
    sections = OrderedDict()
    current = "(머리말)"
    sections[current] = []
    for line in text.split("\n"):
        h = re.match(r"^#(?!#)\s+(.+)$" if h1_only else r"^#{1,2}(?!#)\s+(.+)$", line)
        if h:
            current = h.group(1).strip()[:40]
            sections.setdefault(current, [])
            continue
        sections[current].append(line)
    out = OrderedDict()
    skip = False
    for k, v in sections.items():
        # 06_최종의 고정 부분·행정 항목은 병렬 반복 대상이 아니다
        if STRATEGY_RE.match(k) or ADMIN_RE.search(k):
            continue
        # '검토', '부록', '메모' 이하는 본문이 아니므로 제외
        if re.match(r"^(검토|부록|메모|작성 메모|미작성)", k):
            skip = True
        if skip:
            continue
        body = "\n".join(v)
        # 하위 항목만 담은 상위 헤딩(본문 40자 미만)은 건너뛴다
        if len(re.sub(r"\s", "", body)) < 40:
            continue
        out[k] = body
    return out


def count_kw(text, kw):
    return normalize(text).count(normalize(kw))


def main():
    ap = argparse.ArgumentParser(description="핵심 키워드 반복 검증")
    ap.add_argument("path", help="파일 또는 폴더")
    ap.add_argument("--keywords", help="쉼표로 구분한 키워드")
    ap.add_argument("--auto", action="store_true", help="#태그에서 자동 추출")
    ap.add_argument("--h1", action="store_true",
                    help="`#` 대항목만 섹션으로 본다. 병합본(06_최종.md)에 쓴다")
    ap.add_argument("--min", type=int, default=1,
                    help="섹션당 최소 등장 횟수 (기본 1)")
    args = ap.parse_args()

    p = norm_path(args.path)
    if not os.path.exists(p):
        sys.exit(f"경로를 찾을 수 없습니다: {args.path}")

    # 파일 수집
    files = []
    if os.path.isdir(p):
        files = [os.path.join(p, f) for f in sorted(os.listdir(p)) if f.endswith(".md")]
    else:
        files = [p]
    if not files:
        sys.exit("검사할 .md 파일이 없습니다.")

    whole = "\n".join(open(f, encoding="utf-8").read() for f in files)

    if args.keywords:
        keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    elif args.auto:
        keywords = auto_keywords(whole)
        if not keywords:
            sys.exit("자동 추출 실패. --keywords로 직접 지정해 주세요.")
        print(f"자동 추출된 키워드: {', '.join(keywords)}\n")
    else:
        sys.exit("--keywords 또는 --auto 중 하나가 필요합니다.")

    # 파일이 여러 개면 파일을, 하나면 헤딩을 섹션 축으로 삼는다
    if len(files) > 1:
        units = OrderedDict(
            (os.path.splitext(os.path.basename(f))[0],
             open(f, encoding="utf-8").read())
            for f in files
            if not ADMIN_RE.search(unicodedata.normalize("NFC", os.path.basename(f)))
        )
    else:
        units = split_sections(whole, args.h1)

    # 표 출력
    name_w = max([len(u) for u in units] + [8])
    header = "섹션".ljust(name_w) + " | " + " | ".join(k.center(10) for k in keywords)
    print(header)
    print("-" * len(header))

    totals = {k: 0 for k in keywords}
    gaps = []
    for uname, utext in units.items():
        row = [uname.ljust(name_w)]
        for k in keywords:
            c = count_kw(utext, k)
            totals[k] += c
            mark = "✅" if c >= args.min else "⚠️ "
            row.append(f"{mark}{c:>3}".center(10))
            if c < args.min:
                gaps.append((uname, k))
        print(" | ".join(row))

    print("-" * len(header))
    print("합계".ljust(name_w) + " | " +
          " | ".join(f"{totals[k]:>3}".center(10) for k in keywords))

    # 진단
    print("\n[진단]")
    if not gaps:
        print("  ✅ 모든 섹션에 세 키워드가 모두 등장한다. 병렬 반복이 지켜지고 있다.")
    else:
        print(f"  ⚠️  {len(gaps)}곳에서 키워드가 누락됐다:")
        for uname, k in gaps[:15]:
            print(f"     - '{uname}' 에 '{k}' 없음")
        if len(gaps) > 15:
            print(f"     … 외 {len(gaps)-15}곳")
        print("\n  누락이 의도된 것인지 확인하라. 특정 키워드가 배경에만 나오고")
        print("  개발내용·사업화에서 사라지면 심사자에게 각인되지 않는다.")

    # 편중 진단
    vals = list(totals.values())
    if vals and max(vals) > 0:
        ratio = max(vals) / max(min(vals), 1)
        if ratio >= 3:
            weak = [k for k, v in totals.items() if v == min(vals)]
            print(f"\n  ⚠️  키워드 간 편중이 크다 (최다/최소 = {ratio:.1f}배).")
            print(f"     '{', '.join(weak)}' 의 비중이 낮다. 실질적으로 축이 2개인지 검토하라.")


if __name__ == "__main__":
    main()
