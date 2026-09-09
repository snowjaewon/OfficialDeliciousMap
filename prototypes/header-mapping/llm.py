# PROTOTYPE: 헤더 매핑 LLM 호출 + 채점. Throwaway.
import os, json, re, sys, time, hashlib
from google import genai
from google.genai import types

ENV=dict(os.environ)
def load_env():
    """저장소 루트의 .env 에서 GEMINI_API_KEY, GEMINI_MODEL 을 읽는다(환경변수가 우선)."""
    d=os.path.abspath(os.path.dirname(__file__))
    while d!=os.path.dirname(d):
        p=os.path.join(d,".env")
        if os.path.exists(p):
            for line in open(p,encoding="utf-8"):
                line=line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k,v=line.split("=",1); ENV.setdefault(k,v.strip())
            return
        d=os.path.dirname(d)
load_env()
MODEL=os.environ.get("GEMINI_MODEL",ENV.get("GEMINI_MODEL","gemini-3.6-flash"))
client=genai.Client(api_key=ENV["GEMINI_API_KEY"])

SYSTEM="""너는 한국 지방자치단체 '업무추진비 집행내역' 표의 헤더 매핑기다.
입력은 원본 파일(엑셀·PDF·HTML)의 상위 몇 행을 그대로 옮긴 격자(행 번호 0부터, 열 번호 0부터)다.
행 추출은 코드가 한다. 너는 다음만 판정한다.

1. layout: "table"(열이 고정된 표) / "key_value"(항목명-값 쌍이 한 건을 이루는 카드형) / "none"(표가 없음: 표지·안내문 등).
2. header_rows: 열 이름이 적힌 행 번호 목록. 제목·기관명·'단위: 원'·'□ 세부내역' 같은 행은 헤더가 아니다. 헤더가 두 줄(상위 헤더 + 하위 헤더)이면 둘 다 넣는다. 헤더 행이 아예 없으면 빈 배열.
3. data_start_row: 실제 집행 1건이 처음 시작하는 행. '계'·'합계'·'총계' 같은 요약 행은 건너뛴다. 데이터가 없으면 null.
4. columns: 열마다 역할 하나. 역할:
   - date: 집행(사용·결제·승인)일. 날짜와 시각이 한 칸이면 date.
   - month / day: 날짜가 '월'과 '일' 두 칸으로 갈라진 경우에만.
   - time: 시각만 있는 칸.
   - dept: 부서명. 사람 직함(구청장·과장·주무관)이나 '사용자'는 user다.
   - user: 사용자·직위.
   - place: 상호(식당·가맹점·거래처·채주·사용처·업소명). 주소만 있는 칸은 address. '사용장소'가 동네 이름이고 '가맹점명'이 따로 있으면 가맹점명이 place다.
   - purpose: 집행목적·내역·적요·사용내용.
   - amount: 집행 금액. 인원수·건수와 혼동하지 말 것.
   - count: 대상 인원수. method: 결제방법. category: 비목·예산과목·구분. address: 주소. seq: 연번. other: 나머지.
   판정 근거는 헤더 글자뿐 아니라 아래 데이터 행의 값(날짜 모양, 숫자 크기, 상호 같은 문자열)도 함께 본다. 헤더 행이 없어도 데이터 값으로 역할을 추정한다.
5. amount_unit: "won" / "thousand_won" / "unknown". 헤더나 상단 행에 '천원'이 있으면 thousand_won, '(원)'·'단위: 원' 이면 won. 아무 표기가 없으면 데이터 값의 크기로 판단한다(식사 한 건이 수만~수십만 원이므로 값이 두세 자리면 천원 단위일 가능성이 크다).
6. year_hint: 날짜 칸에 연도가 없을 때 제목 행에서 읽은 연도(예: "2026"). 없으면 null.

JSON만 출력한다."""

SCHEMA={
 "type":"object",
 "properties":{
  "layout":{"type":"string","enum":["table","key_value","none"]},
  "header_rows":{"type":"array","items":{"type":"integer"}},
  "data_start_row":{"type":["integer","null"]},
  "columns":{"type":"array","items":{"type":"object","properties":{
      "col":{"type":"integer"},
      "role":{"type":"string","enum":["date","month","day","time","dept","user","place","purpose","amount","count","method","category","address","seq","other"]},
      "header_text":{"type":"string"}},"required":["col","role","header_text"]}},
  "amount_unit":{"type":"string","enum":["won","thousand_won","unknown"]},
  "year_hint":{"type":["string","null"]},
  "note":{"type":"string"}
 },
 "required":["layout","header_rows","data_start_row","columns","amount_unit","year_hint"]
}

def render(grid):
    lines=[]
    for i,row in enumerate(grid["rows"]):
        cells=[f"[{j}]{c}" for j,c in enumerate(row) if c!=""]
        lines.append(f"r{i}: "+" | ".join(cells))
    return "\n".join(lines)

def call(grid, fmt, title):
    prompt=f"파일 형식: {fmt}\n게시글 제목: {title}\n시트/표: {grid['sheet']}\n\n격자:\n{render(grid)}"
    t0=time.time()
    resp=client.models.generate_content(
        model=MODEL, contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM, temperature=0,
            response_mime_type="application/json", response_json_schema=SCHEMA,
            thinking_config=types.ThinkingConfig(thinking_level="minimal")))
    um=resp.usage_metadata
    return json.loads(resp.text), {"in":um.prompt_token_count,"out":um.candidates_token_count,"thought":getattr(um,"thoughts_token_count",None),"sec":round(time.time()-t0,2)}, prompt

def norm(s): return re.sub(r"[\s\u3000]+","",s or "")

def score(gold, ans, grid):
    r={"file":None}
    if gold.get("layout") in ("none","key_value"):
        r["layout_ok"]= ans["layout"]==gold["layout"]
        if "unit" in gold: r["unit_ok"]= ans["amount_unit"]==gold["unit"]
        return r
    r["layout_ok"]= ans["layout"]=="table"
    r["hdr_ok"]= sorted(ans["header_rows"])==sorted(gold["hdr"])
    rows=grid["rows"]
    def header_of(col):
        txt=[]
        for h in ans["header_rows"]:
            if h<len(rows) and col<len(rows[h]): txt.append(rows[h][col])
        return norm("|".join(t for t in txt if t))
    byrole={}
    for c in ans["columns"]: byrole.setdefault(c["role"],[]).append(c["col"])
    for role in ["date","dept","place","purpose","amount"]:
        g=gold.get(role,"")
        if f"{role}_idx" in gold:
            r[f"{role}_ok"]= gold[f"{role}_idx"] in byrole.get(role,[]); continue
        got=byrole.get(role,[])
        if role=="date" and not got and ("month" in byrole and "day" in byrole): got=byrole["month"]
        if g=="":
            r[f"{role}_ok"]= len(got)==0
        else:
            gn=norm(g); hits=[header_of(c) for c in got]
            r[f"{role}_ok"]= any(h and (gn==h or gn.split("|")[0] in h or h in gn) for h in hits)
    r["unit_ok"]= ans["amount_unit"]==gold["unit"]
    return r

if __name__=="__main__":
    grids=json.load(open("grids.json",encoding="utf-8"))
    gold=json.load(open("gold.json",encoding="utf-8"))
    only=set(sys.argv[1:])
    cache_p="llm_cache.json"
    cache=json.load(open(cache_p,encoding="utf-8")) if os.path.exists(cache_p) else {}
    results=[]
    for g in grids:
        if not g["grids"] or g["file"] not in gold: continue
        if only and g["file"] not in only: continue
        grid=g["grids"][0]
        key=hashlib.md5((MODEL+SYSTEM+json.dumps(grid,ensure_ascii=False)).encode()).hexdigest()
        if key in cache and not only: ans,usage=cache[key]["ans"],cache[key]["usage"]
        else:
            try: ans,usage,_=call(grid,g["fmt"],g["title"])
            except Exception as e: print("ERR",g["file"],repr(e)[:200]); continue
            cache[key]={"ans":ans,"usage":usage}; json.dump(cache,open(cache_p,"w",encoding="utf-8"),ensure_ascii=False,indent=1)
        sc=score(gold[g["file"]],ans,grid); sc["file"]=g["file"]; sc["usage"]=usage; sc["ans"]=ans
        results.append(sc)
        flags=" ".join(f"{k[:-3]}{'✓' if v else '✗'}" for k,v in sc.items() if k.endswith("_ok"))
        print(f"{g['file']:40s} {flags}  in={usage['in']} out={usage['out']} {usage['sec']}s")
    json.dump(results,open("results.json","w",encoding="utf-8"),ensure_ascii=False,indent=1)
    keys=["layout_ok","hdr_ok","date_ok","dept_ok","place_ok","purpose_ok","amount_ok","unit_ok"]
    print("\n== summary", MODEL, len(results),"files")
    for k in keys:
        n=[r[k] for r in results if k in r]
        if n: print(f"  {k:12s} {sum(n)}/{len(n)}  {100*sum(n)/len(n):.0f}%")
    allok=[all(v for k,v in r.items() if k.endswith("_ok")) for r in results]
    print(f"  file-level all-correct {sum(allok)}/{len(allok)}  {100*sum(allok)/len(allok):.0f}%")
    print("  tokens in/out avg", sum(r["usage"]["in"] for r in results)//len(results), sum(r["usage"]["out"] for r in results)//len(results))
