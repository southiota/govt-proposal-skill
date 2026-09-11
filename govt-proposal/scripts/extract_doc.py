#!/usr/bin/env python3
"""
공고문·작성양식 등 문서에서 텍스트를 추출한다.

지원: .hwpx (XML 기반, 권장) / .hwp (구형 바이너리, olefile 필요) / .docx / .pdf / .txt / .md
.hwp는 표 구조가 보존되지 않으므로, 양식처럼 구조가 중요하면 HWPX로 다시 저장하는 편이 낫다.

사용:
    python extract_doc.py 공고문.hwpx
    python extract_doc.py 공고문.hwpx -o 00_입력/공고문.md
    python extract_doc.py 양식.hwpx --tables      # 표 구조 보존 시도
"""
import argparse
import html
import os
import re
import sys
import unicodedata
import zipfile


def norm(path):
    """macOS NFD 파일명 대응: 실제 존재하는 경로를 찾아 반환."""
    if os.path.exists(path):
        return path
    d = os.path.dirname(path) or "."
    base = os.path.basename(path)
    if not os.path.isdir(d):
        return path
    target = unicodedata.normalize("NFC", base)
    for f in os.listdir(d):
        if unicodedata.normalize("NFC", f) == target:
            return os.path.join(d, f)
    return path


def clean(text):
    text = html.unescape(text)
    text = text.replace("​", "").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def classify_table(rows):
    """표의 '모양'을 판정한다. 정부 양식의 표는 대부분 진짜 표가 아니다.

    한글 양식은 글 쓰는 자리도 표로 만든다. 그래서 추출하면 전부 표처럼 보이는데,
    실제로는 네 가지가 섞여 있고 대응이 전혀 다르다. 이 판정을 사람이 매번 하면
    반드시 틀리므로 여기서 이름표를 붙여 내보낸다.

    rows: [[셀문자열, ...], ...]
    반환: (유형, 지시문)
    """
    if not rows:
        return "빈표", "무시한다"
    ncol = max(len(r) for r in rows)
    nrow = len(rows)
    filled = [[c.strip() for c in r] for r in rows]
    flat = [c for r in filled for c in r if c]

    # 전부 ※ 안내문 — 채우는 칸이 아니라 작성 지침이다
    if flat and all(c.startswith(("※", "*", "‧")) for c in flat):
        return "지침칸", "작성 지침이다. 여기에 내용을 쓰지 않는다. 지침 내용을 02_이해.md 에 옮겨 적고 본문에 반영한다"

    # 1열 — 표가 아니다
    if ncol <= 1:
        if not flat:
            return "본문칸", "글 쓰는 자리다. 표가 아니다. 여기에는 블록(상위 메시지 + 세부 + 입증 방안)을 쓰고, 마크다운 표를 만들지 않는다"
        return "머리글칸", "이미 적혀 있는 문구다. 그대로 두고 내용을 덧붙이지 않는다"

    # 1행짜리 띠 — 항목 제목이다. 양식마다 배치가 다르다.
    #   `| 1. 기술개발 목표 | |`   제목이 왼쪽, 오른쪽 빈칸   (디딤돌)
    #   `| 1 | 지원 필요성 |`      번호가 왼쪽, 제목이 오른쪽 (과기부)
    #   `| 1 | | 사업신청서 표지 |` 번호·빈칸·제목             (콘진원)
    # 공통점은 '한 행이고, 채워진 칸이 두 개 이하이며, 전부 짧다'는 것이다.
    if nrow == 1 and ncol <= 3:
        vals = [c for c in filled[0] if c]
        if vals and len(vals) <= 2 and all(len(c) <= 40 for c in vals):
            return "제목띠", "양식 항목의 제목이다. 헤딩으로 옮기고, 내용은 이어지는 본문칸이나 표 밖 문단에 쓴다"

    # 2열이고 왼쪽만 채워져 있다 — 라벨:값
    if ncol == 2 and all(r[0].strip() for r in filled if r) and not any(
            len(r) > 1 and r[1].strip() for r in filled):
        return "라벨값표", "왼쪽 라벨은 그대로 두고 오른쪽 칸만 채운다. 칸 안에서도 2분할로 쓴다"

    return f"데이터표({ncol}열)", "진짜 표다. 열 제목을 그대로 두고 칸을 채운다. 칸 안에서도 2분할로 쓴다"


def from_hwpx(path, keep_tables=False):
    """HWPX: Contents/section*.xml 에서 문단 텍스트를 추출한다.

    keep_tables=True 이면 <hp:tbl> 안의 <hp:tr>/<hp:tc> 경계를 인식해
    행은 줄바꿈으로, 셀은 ' | '로 구분한다. 정부 양식은 거의 전부가 표이므로
    이 구조가 사라지면 하위 문항·칸 구성·지침 위치가 전부 뭉개진다.
    """
    def para_text(xml_fragment):
        runs = re.findall(r"<hp:t[^>]*>(.*?)</hp:t>", xml_fragment, re.S)
        return "".join(re.sub(r"<[^>]+>", "", r) for r in runs)

    out = []
    with zipfile.ZipFile(path) as z:
        sections = sorted(
            n for n in z.namelist()
            if re.match(r"Contents/section\d+\.xml$", n)
        )
        if not sections:
            raise ValueError("HWPX 구조가 아닙니다 (Contents/section*.xml 없음)")

        for name in sections:
            xml = z.read(name).decode("utf-8", errors="replace")

            if not keep_tables:
                for para in re.findall(r"<hp:p\b.*?</hp:p>", xml, re.S):
                    out.append(para_text(para))
                continue

            # 표와 표 밖 문단을 문서 순서대로 걷는다
            pos = 0
            for tbl in re.finditer(r"<hp:tbl\b.*?</hp:tbl>", xml, re.S):
                before = xml[pos:tbl.start()]
                for para in re.findall(r"<hp:p\b.*?</hp:p>", before, re.S):
                    out.append(para_text(para))
                rows = []
                for tr in re.findall(r"<hp:tr\b.*?</hp:tr>", tbl.group(0), re.S):
                    cells = []
                    for tc in re.findall(r"<hp:tc\b.*?</hp:tc>", tr, re.S):
                        ps = re.findall(r"<hp:p\b.*?</hp:p>", tc, re.S)
                        cell = " / ".join(t for t in (para_text(p).strip() for p in ps) if t)
                        cells.append(cell)
                    rows.append(cells)
                kind, how = classify_table(rows)
                out.append(f"<!-- 표:{kind} — {how} -->")
                for cells in rows:
                    out.append("| " + " | ".join(cells) + " |")
                out.append("")
                pos = tbl.end()
            for para in re.findall(r"<hp:p\b.*?</hp:p>", xml[pos:], re.S):
                out.append(para_text(para))
    return "\n".join(out)


def from_hwp(path):
    """구형 HWP 5.0 (OLE 복합 문서). BodyText 섹션을 zlib 해제 후 문단 레코드에서 텍스트만 뽑는다.

    표 안의 텍스트는 셀 순서대로 이어 붙으므로 표 구조는 보존되지 않는다.
    공고문처럼 읽어서 판단하는 용도로는 충분하고, 양식처럼 구조가 중요한 문서는
    HWPX로 다시 저장하도록 안내하는 편이 낫다.
    """
    try:
        import olefile
    except ImportError:
        sys.exit(
            ".hwp 추출에 olefile이 필요합니다:\n"
            "    pip install olefile --break-system-packages\n"
            "설치가 어려우면 한글에서 HWPX로 다시 저장해 주세요."
        )
    import struct
    import zlib

    ole = olefile.OleFileIO(path)
    try:
        header = ole.openstream("FileHeader").read()
        compressed = bool(header[36] & 1)

        def records(data):
            i = 0
            while i + 4 <= len(data):
                h = struct.unpack("<I", data[i:i + 4])[0]
                tag, size = h & 0x3FF, (h >> 20) & 0xFFF
                i += 4
                if size == 0xFFF:              # 확장 길이
                    size = struct.unpack("<I", data[i:i + 4])[0]
                    i += 4
                yield tag, data[i:i + size]
                i += size

        out = []
        sections = sorted((s for s in ole.listdir() if s[0] == "BodyText"),
                          key=lambda s: s[1])
        if not sections:
            raise ValueError("BodyText 스트림이 없습니다")

        for s in sections:
            raw = ole.openstream(s).read()
            data = zlib.decompress(raw, -15) if compressed else raw
            for tag, body in records(data):
                if tag != 67:                  # HWPTAG_PARA_TEXT
                    continue
                buf, i = [], 0
                while i + 1 < len(body):
                    c = struct.unpack("<H", body[i:i + 2])[0]
                    i += 2
                    if c < 32:                 # 컨트롤 문자
                        # HWP 5.0: 문자 컨트롤(0,10,13,24~31)은 1 WCHAR,
                        # 인라인(4~9,19~23)·확장(1~3,11~18) 컨트롤은 8 WCHAR(16바이트)
                        if c in (10, 13):
                            buf.append("\n")
                        elif c == 9:
                            buf.append("\t"); i += 14
                        elif c in (0, 24, 25, 26, 27, 28, 29, 30, 31):
                            pass
                        else:
                            i += 14
                        continue
                    if 0xD800 <= c <= 0xDFFF:  # 짝 없는 서로게이트
                        continue
                    buf.append(chr(c))
                out.append("".join(buf))
        return "\n".join(out)
    finally:
        ole.close()


def from_docx(path):
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    out = []
    for para in re.findall(r"<w:p\b.*?</w:p>", xml, re.S):
        runs = re.findall(r"<w:t[^>]*>(.*?)</w:t>", para, re.S)
        out.append("".join(runs))
    return "\n".join(out)


def from_pdf(path):
    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader  # type: ignore
        except ImportError:
            sys.exit("PDF 추출에 pypdf가 필요합니다: pip install pypdf")
    reader = PdfReader(path)
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def main():
    ap = argparse.ArgumentParser(description="문서에서 텍스트 추출")
    ap.add_argument("path", help="입력 파일 (.hwpx/.docx/.pdf/.txt/.md)")
    ap.add_argument("-o", "--out", help="출력 파일 (없으면 표준출력)")
    ap.add_argument("--tables", action="store_true",
                    help="표 구조를 파이프(|)로 대략 보존")
    args = ap.parse_args()

    path = norm(args.path)
    if not os.path.exists(path):
        sys.exit(f"파일을 찾을 수 없습니다: {args.path}")

    ext = os.path.splitext(path)[1].lower()

    try:
        if ext == ".hwpx":
            text = from_hwpx(path, args.tables)
        elif ext == ".hwp":
            text = from_hwp(path)
        elif ext == ".docx":
            text = from_docx(path)
        elif ext == ".pdf":
            text = from_pdf(path)
        elif ext in (".txt", ".md", ".csv"):
            text = open(path, encoding="utf-8", errors="replace").read()
        else:
            sys.exit(f"지원하지 않는 확장자입니다: {ext}")
    except zipfile.BadZipFile:
        sys.exit("파일이 손상되었거나 형식이 다릅니다. 확장자를 확인해 주세요.")

    if args.tables and ext != ".hwpx":
        print("(참고) --tables 는 .hwpx 에서만 동작합니다. 표 구조가 필요하면 HWPX로 저장하세요.",
              file=sys.stderr)

    text = clean(text)

    if args.out:
        outp = args.out
        os.makedirs(os.path.dirname(outp) or ".", exist_ok=True)
        with open(outp, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"저장: {outp}  ({len(text):,}자)")
    else:
        print(text)


if __name__ == "__main__":
    main()
