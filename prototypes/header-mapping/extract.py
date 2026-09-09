# PROTOTYPE: 원본 → 상위 N행 격자(헤더 매핑 입력). Throwaway.
import os, json, hashlib, re, sys, io, warnings
warnings.filterwarnings("ignore")
N_ROWS=12; N_COLS=16
def clean(v):
    if v is None: return ""
    s=str(v).strip().replace("\n"," / ")
    return s[:40]
def from_xlsx(p):
    import openpyxl
    wb=openpyxl.load_workbook(p,read_only=True,data_only=True)
    out=[]
    for ws in wb.worksheets:
        rows=[]
        for r in ws.iter_rows(max_row=60,values_only=True):
            cells=[clean(c) for c in r][:N_COLS]
            if any(cells): rows.append(cells)
            if len(rows)>=N_ROWS: break
        if rows: out.append({"sheet":ws.title,"rows":rows,"total_rows":ws.max_row})
        if len(out)>=2: break
    return out
def from_xls(p):
    import xlrd
    wb=xlrd.open_workbook(p); out=[]
    for ws in wb.sheets():
        rows=[]
        for i in range(min(ws.nrows,60)):
            cells=[clean(c.value if c.ctype!=3 else xlrd.xldate_as_datetime(c.value,wb.datemode).date()) for c in ws.row(i)][:N_COLS]
            if any(cells): rows.append(cells)
            if len(rows)>=N_ROWS: break
        if rows: out.append({"sheet":ws.name,"rows":rows,"total_rows":ws.nrows})
        if len(out)>=2: break
    return out
def from_pdf(p):
    import pdfplumber
    out=[]
    with pdfplumber.open(p) as pdf:
        pg=pdf.pages[0]
        tables=pg.extract_tables()
        text=pg.extract_text() or ""
        if tables:
            t=tables[0]
            rows=[[clean(c) for c in r][:N_COLS] for r in t[:N_ROWS]]
            out.append({"sheet":"page1/table1","rows":rows,"total_rows":sum(len(x) for x in tables),"pages":len(pdf.pages),"text_head":text[:300]})
        else:
            out.append({"sheet":"page1/no-table","rows":[[l] for l in text.splitlines()[:N_ROWS]],"total_rows":0,"pages":len(pdf.pages),"text_head":text[:300]})
    return out
def from_html(p):
    from bs4 import BeautifulSoup
    s=BeautifulSoup(open(p,encoding="utf-8").read(),"lxml")
    out=[]
    def score(t):
        head=" ".join(th.get_text(" ",strip=True) for th in t.find_all(["th","td"])[:20])
        return -(("금액" in head)*500+sum(k in head for k in ["장소","목적","일자","일시","집행","사용","내용"])*100+len(t.find_all("tr")))
    tables=sorted(s.find_all("table"),key=score)
    for t in tables[:1]:
        rows=[]
        for tr in t.find_all("tr")[:N_ROWS]:
            rows.append([clean(td.get_text(" ",strip=True)) for td in tr.find_all(["th","td"])][:N_COLS])
        out.append({"sheet":"largest-table","rows":rows,"total_rows":len(t.find_all("tr"))})
    if not out:
        # 은평·관악·서대문형 라인: li/dl 구조. 텍스트 상위 몇 줄.
        body=s.get_text("\n",strip=True)
        lines=[l for l in body.splitlines() if l.strip()]
        i=next((k for k,l in enumerate(lines) if re.search(r"집행|사용|금액",l)),0)
        out.append({"sheet":"no-table/text","rows":[[l[:80]] for l in lines[i:i+N_ROWS]],"total_rows":0})
    return out
def sniff(p):
    b=open(p,"rb").read(4096)
    if b[:4]==b"%PDF": return "pdf"
    if b[:2]==b"PK": return "hwpx" if b"mimetype" in b[:80] and b"hwp" in b[:200] else "xlsx"
    if b[:8]==b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        import olefile
        o=olefile.OleFileIO(p); names=[ "/".join(x) for x in o.listdir()]
        return "hwp" if any("FileHeader" in n or "BodyText" in n for n in names) else "xls"
    if b"<html" in b[:400].lower() or b"<!doctype" in b[:400].lower(): return "html"
    return "bin"
log={e["file"]:e for e in json.load(open("fetch_log.json",encoding="utf-8"))}
seen={}; grids=[]
for f in sorted(os.listdir("raw")):
    p=os.path.join("raw",f)
    h=hashlib.md5(open(p,"rb").read()).hexdigest()
    if h in seen: print("dup",f,"=",seen[h]); continue
    seen[h]=f
    k=sniff(p)
    try:
        if k=="xlsx": g=from_xlsx(p)
        elif k=="xls": g=from_xls(p)
        elif k=="pdf": g=from_pdf(p)
        elif k=="html": g=from_html(p)
        else: g=[]; print("skip",f,k)
    except Exception as e:
        g=[]; print("ERR",f,k,repr(e)[:120])
    meta=log.get(f,{})
    grids.append({"file":f,"board":meta.get("board",f.rsplit("_",1)[0]),"title":meta.get("title",""),"fmt":k,"grids":g})
json.dump(grids,open("grids.json","w",encoding="utf-8"),ensure_ascii=False,indent=1)
print(len(grids),"files;", sum(1 for g in grids if g["grids"]),"with grids")
