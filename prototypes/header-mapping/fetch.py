# PROTOTYPE downloader: small sample of real 원본 files per board. Throwaway.
import requests, re, os, sys, json, time
from urllib.parse import urljoin, unquote
from bs4 import BeautifulSoup
UA={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"}
S=requests.Session(); S.headers.update(UA)
os.makedirs("raw",exist_ok=True)
LOG=[]
def sniff(b):
    if b[:4]==b"%PDF": return "pdf"
    if b[:2]==b"PK": return "xlsx" if b"xl/" in b[:4000] or b"[Content_Types]" in b[:200] else "zip"
    if b[:8]==b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1": return "ole"
    if b"DRMONE" in b[:32]: return "drm"
    t=b[:400].lower()
    if b"<html" in t or b"<!doctype" in t: return "html"
    return "bin"
def save(key, url, title, referer=None, n=None):
    try:
        r=S.get(url,headers={"Referer":referer} if referer else {},timeout=60)
        b=r.content; k=sniff(b)
        cd=r.headers.get("Content-Disposition","")
        m=re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)",cd)
        fname=unquote(m.group(1)) if m else ""
        name=f"{key}_{n if n is not None else abs(hash(url))%10000}.{k}"
        open(f"raw/{name}","wb").write(b)
        LOG.append({"file":name,"board":key,"title":title,"url":url,"fmt":k,"size":len(b),"cd":fname,"status":r.status_code})
        print(f"  {name} {k} {len(b)}B  {title[:50]} | {fname[:60]}")
    except Exception as e:
        print(f"  ERR {key} {url} {e}")
def wants(t):  # 2026 first half preferred
    return bool(re.search(r"2026",t)) and bool(re.search(r"(1|2)분기|상반기|0?[1-6]월",t))
def soup(url,**kw):
    r=S.get(url,timeout=60,**kw)
    if not r.encoding or r.encoding.lower()=="iso-8859-1": r.encoding=r.apparent_encoding
    return r, BeautifulSoup(r.text,"lxml")
def list_links(url, pat, referer=None, max_n=3, prefer=wants, **kw):
    r,s=soup(url,**kw); out=[]
    for a in s.find_all("a"):
        h=(a.get("href") or "")+" "+(a.get("onclick") or "")
        if re.search(pat,h):
            tr=a.find_parent("tr") or a.find_parent("li") or a
            out.append((h.strip(), tr.get_text(" ",strip=True)[:120]))
    pref=[o for o in out if prefer(o[1])]
    return (pref or out)[:max_n], r
LIMIT=int(os.environ.get("LIMIT","3"))
TASKS={}
def task(f): TASKS[f.__name__]=f; return f
def run(which):
    for name,fn in TASKS.items():
        if which and name not in which: continue
        print("##",name, flush=True)
        try: fn()
        except Exception as e: print("  FAIL",repr(e))

# ---- 대구 (목록 안 fn_egov_downFile) ----
FN=r"fn_egov_downFile\('([^']+)','(\d+)'"
def daegu(host,menu,key):
    links,_=list_links(f"{host}/index.do?menu_id={menu}",r"fn_egov_downFile",max_n=LIMIT)
    for i,(h,t) in enumerate(links):
        fid,sn=re.search(FN,h).groups()
        save(key,f"{host}/icms/cmm/fms/FileDown.do?atchFileId={fid}&fileSn={sn}",t,n=i)
@task
def daegu_city(): daegu("https://www.daegu.go.kr","00000084","daegu_city")
@task
def daegu_buk(): daegu("https://www.buk.daegu.kr","00000122","daegu_buk")
@task
def daegu_nam(): daegu("https://www.nam.daegu.kr","00001247","daegu_nam")
# ---- 부산 rfc3 (view → download.<key>) ----
def rfc3(host,sitekey,boardId,key,extra=""):
    links,_=list_links(f"{host}/board/list.{sitekey}?boardId={boardId}{extra}",r"view\.",max_n=LIMIT)
    for i,(h,t) in enumerate(links):
        r,s=soup(urljoin(host,h.split()[0]))
        dl=[a.get("href") for a in s.find_all("a") if re.search(r"download\.",a.get("href") or "")]
        if dl: save(key,urljoin(host,dl[0]),t,referer=host,n=i)
        else: print("  no attach:",t[:50])
@task
def busan_haeundae(): rfc3("https://www.haeundae.go.kr","do","BBS_0000004","busan_haeundae")
@task
def busan_busanjin(): rfc3("https://www.busanjin.go.kr","busanjin","BBS_0000023","busan_busanjin","&menuCd=DOM_000000109001003000&contentsSid=276")
@task
def busan_dongnae(): rfc3("https://www.dongnae.go.kr","dongnae","BBS_0000200","busan_dongnae")
@task
def busan_seo(): rfc3("https://www.bsseogu.go.kr","bsseogu","BBS_0000151","busan_seo")
@task
def busan_sasang(): rfc3("https://www.sasang.go.kr","sasang","BBS_0000175","busan_sasang")
@task
def busan_gijang():
    u="https://www.gijang.go.kr/board/list.gijang?boardId=BBS_0000147&menuCd=DOM_000000101002014000&paging=ok&categoryCode1=000&startPage=2"
    r,s=soup(u)
    open("raw/busan_gijang_0.html","w",encoding="utf-8").write(r.text)
    LOG.append({"file":"busan_gijang_0.html","board":"busan_gijang","title":"목록 HTML 표 2쪽","url":u,"fmt":"html","size":len(r.content)})
# ---- 서울 ----
def direct(key,listurl,pat,base):
    links,_=list_links(listurl,pat,max_n=LIMIT)
    for i,(h,t) in enumerate(links): save(key,urljoin(base,h.split()[0]),t,n=i)
@task
def seoul_gwangjin(): direct("seoul_gwangjin","https://www.gwangjin.go.kr/portal/bbs/B0000027/list.do?menuNo=201646",r"fileDown\.do","https://www.gwangjin.go.kr")
@task
def seoul_yongsan(): direct("seoul_yongsan","https://www.yongsan.go.kr/portal/bbs/B0000030/list.do?menuNo=200140",r"fileDown\.do","https://www.yongsan.go.kr")
@task
def seoul_jongno(): direct("seoul_jongno","https://www.jongno.go.kr/portal/bbs/selectBoardList.do?bbsId=BBSMSTR_000000001167&menuId=110210",r"FileDown\.do","https://www.jongno.go.kr")
@task
def seoul_seongdong(): direct("seoul_seongdong","https://www.sd.go.kr/main/selectBbsNttList.do?bbsNo=172&key=1330",r"downloadBbsFileStr","https://www.sd.go.kr/main/")
@task
def seoul_mapo(): direct("seoul_mapo","https://www.mapo.go.kr/site/main/board/expense/list",r"/file/download/uu/","https://www.mapo.go.kr")
@task
def seoul_gangnam(): direct("seoul_gangnam","https://www.gangnam.go.kr/board/B_000673/list.do?mid=ID05_04200502",r"/file/.*download","https://www.gangnam.go.kr")
@task
def seoul_gangseo():
    links,_=list_links("https://www.gangseo.seoul.kr/gs030325",r"/gs030325/\d+",max_n=LIMIT)
    for i,(h,t) in enumerate(links):
        r,s=soup(urljoin("https://www.gangseo.seoul.kr",h.split()[0]))
        dl=[a.get("href") for a in s.find_all("a") if "getFile" in (a.get("href") or "")]
        if dl: save("seoul_gangseo",urljoin("https://www.gangseo.seoul.kr",dl[0]),t,n=i)
def save_html(key,url,title,**kw):
    r,s=soup(url,**kw)
    open(f"raw/{key}.html","w",encoding="utf-8").write(r.text)
    LOG.append({"file":f"{key}.html","board":key.rsplit("_",1)[0],"title":title,"url":url,"fmt":"html","size":len(r.content)})
    print("  ",key,len(r.content))
@task
def seoul_city_html():
    r,s=soup("https://opengov.seoul.go.kr/expense/list")
    ids=[(a.get("href"),a.get_text(" ",strip=True)) for a in s.find_all("a") if re.search(r"/expense/\d+",a.get("href") or "")]
    for i,(h,t) in enumerate(ids[:2]): save_html(f"seoul_city_{i}",urljoin("https://opengov.seoul.go.kr",h),t[:80])
@task
def seoul_seodaemun_html():
    r=S.post("https://www.sdm.go.kr/admininfo/budget/openmoney.do",data={"cp":"1","searchGUBUN":"","searchDept":"","searchYear":"2026","searchMonth":"06"},timeout=60)
    r.encoding="cp949"; open("raw/seoul_seodaemun_0.html","w",encoding="utf-8").write(r.text)
    LOG.append({"file":"seoul_seodaemun_0.html","board":"seoul_seodaemun","title":"2026-06 HTML 라인 (천원)","url":r.url,"fmt":"html","size":len(r.content)})
    print("   seodaemun",len(r.content))
@task
def seoul_gwanak_html(): save_html("seoul_gwanak_0","https://www.gwanak.go.kr/site/gwanak/estimate/estimateList.do","HTML 카드형 목록")
@task
def seoul_eunpyeong_html(): save_html("seoul_eunpyeong_0","https://www.ep.go.kr/www/selectJobPrtnCtWebList.do?key=666&pageUnit=50","HTML 라인 목록")
# ---- 광주 ----
def gwangju_es(host,mid,bid,key):
    links,_=list_links(f"{host}/board.es?mid={mid}&bid={bid}",r"list_no=\d+",max_n=LIMIT)
    for i,(h,t) in enumerate(links):
        ln=re.search(r"list_no=(\d+)",h).group(1)
        save(key,f"{host}/boardDownload.es?mid={mid}&bid={bid}&list_no={ln}&seq=1",t,referer=host,n=i)
@task
def gwangju_nam(): gwangju_es("https://www.namgu.gwangju.kr","a10304100000","0007","gwangju_nam")
@task
def gwangju_buk(): gwangju_es("https://bukgu.gwangju.kr","a10502050000","0004","gwangju_buk")
@task
def gwangju_dong(): gwangju_es("https://gjdc.donggu.kr","a10801040000","0020","gwangju_dong")
@task
def gwangju_city():
    links,_=list_links("https://www.gwangju.go.kr/boardList.do?boardId=BD_0000000252&recordCnt=30",r"boardView\.do.*seq=\d+",max_n=LIMIT)
    for i,(h,t) in enumerate(links):
        seq=re.search(r"seq=(\d+)",h).group(1)
        save("gwangju_city",f"https://www.gwangju.go.kr/fileDownload.do?fileSe=BB&fileKey=BD_0000000252%7C{seq}&fileSn=1&boardId=BD_0000000252&seq={seq}",t,n=i)
# ---- 인천 ----
@task
def incheon_michuhol():
    links,r=list_links("https://www.michuhol.go.kr/main/board/list.do?board_code=business_promotion",r"view\.do\?sq=",max_n=LIMIT)
    print("   list bytes",len(r.content))
    for i,(h,t) in enumerate(links):
        r,s=soup(urljoin("https://www.michuhol.go.kr/main/board/",h.split()[0]))
        dl=[a.get("href") for a in s.find_all("a") if "file_down" in (a.get("href") or "")]
        if dl: save("incheon_michuhol",urljoin("https://www.michuhol.go.kr",dl[0]),t,n=i)
        else: print("  no attach",t[:40], len(r.content))
@task
def incheon_yeongjong():
    for b in ["mn_exp_cap","mn_exp_head"]:
        links,_=list_links(f"https://www.yeongjong.go.kr/main/pst/list.do?pst_id={b}",r"pst_sn=",max_n=2)
        for i,(h,t) in enumerate(links):
            r,s=soup(urljoin("https://www.yeongjong.go.kr/main/pst/",h.split()[0]))
            dl=[a.get("href") for a in s.find_all("a") if "TP=dn" in (a.get("href") or "")]
            if dl: save("incheon_yeongjong",urljoin("https://www.yeongjong.go.kr",dl[0].replace("&amp;","&")),t,n=f"{b}_{i}")
            else: print("  no attach",t[:40])
def incheon_bbs(base,bcd,key,extra=""):
    links,r=list_links(f"{base}/bbs/bbsMsgList.do?bcd={bcd}{extra}",r"msg_seq=\d+",max_n=LIMIT)
    print("   list bytes",len(r.content))
    for i,(h,t) in enumerate(links):
        seq=re.search(r"msg_seq=(\d+)",h).group(1)
        save(key,f"{base}/bbs/bbsMsgFileDown.do?bcd={bcd}&msg_seq={seq}&fileno=1",t,referer=base,n=i)
@task
def incheon_jemulpo(): incheon_bbs("https://www.jemulpo.go.kr/main","opendata","incheon_jemulpo")
@task
def incheon_gyeyang(): incheon_bbs("https://www.gyeyang.go.kr/open_content/main","board_14","incheon_gyeyang","&cate1=94")
@task
def incheon_ganghwa(): incheon_bbs("https://www.ganghwa.go.kr/open_content/main","operation","incheon_ganghwa")
@task
def incheon_city():
    for b in ["OPEN010305","OPEN010301"]:
        links,_=list_links(f"https://www.incheon.go.kr/open/{b}",rf"/open/{b}/\d+",max_n=2)
        for i,(h,t) in enumerate(links):
            gid=re.search(rf"{b}/(\d+)",h).group(1)
            save("incheon_city",f"https://www.incheon.go.kr/comm/getFile?srvcId=BBSTY1&upperNo={gid}&fileTy=ATTACH&fileNo=1",t,n=f"{b}_{i}")
# ---- 울산 ----
@task
def ulsan_namgu(): direct("ulsan_namgu","https://www.ulsannamgu.go.kr/cop/bbs/selectBoardList.do?bbsId=PrmtFee2",r"FileDown\.do","https://www.ulsannamgu.go.kr")
@task
def ulsan_buk():
    links,_=list_links("https://www.bukgu.ulsan.kr/lay1/bbs/S1T136C1896/A/348/list.do",r"article_seq=",max_n=LIMIT)
    for i,(h,t) in enumerate(links):
        r,s=soup(urljoin("https://www.bukgu.ulsan.kr/lay1/bbs/S1T136C1896/A/348/",h.split()[0]))
        dl=[a.get("href") for a in s.find_all("a") if "download.do?uuid" in (a.get("href") or "")]
        if dl: save("ulsan_buk",urljoin("https://www.bukgu.ulsan.kr",dl[0]),t,n=i)
@task
def ulsan_html():
    save_html("ulsan_junggu_0","https://www.junggu.ulsan.kr/mayor/board/list.ulsan?boardId=BBS_0000006&listRow=30&listCel=1&menuCd=DOM_000000201005000000","목록 = 집행내역 표")
    save_html("ulsan_donggu_0","https://www.donggu.ulsan.kr/mayor/expense/view.do?ymd2=20260626","상세 표")
    save_html("ulsan_city_0","https://www.ulsan.go.kr/u/rep/transfer/ecnmy/list.ulsan?mId=001004003002000000&useDe=2026-06-26","상세 표 (천원)")
# ---- 대전 ----
def daejeon_egov(host,bbs,key):
    links,r=list_links(f"{host}/bbs/{bbs}/list.do?pageIndex=1",r"FileDown\.do|zipDownload|atchFileId|fn_egov",max_n=LIMIT)
    print("   list bytes",len(r.content))
    for i,(h,t) in enumerate(links):
        m=re.search(r"atchFileId=([^&'\"\s]+)",h) or re.search(r"'([A-Za-z0-9_]{15,})'",h)
        if m: save(key,f"{host}/cmm/fms/FileDown.do?atchFileId={m.group(1)}&fileSn=0",t,n=i)
        else: print("  ?",h[:100])
@task
def daejeon_junggu(): daejeon_egov("https://www.djjunggu.go.kr","BBSMSTR_000000000103","daejeon_junggu")
@task
def daejeon_yuseong(): daejeon_egov("https://www.yuseong.go.kr","BBSMSTR_000000000111","daejeon_yuseong")
@task
def daejeon_city():
    for bseq in [694,1186]:
        r=S.post("https://www.daejeon.go.kr/drh/open/drhDataOpen/drhDataOpenBoardView.do",data={"boardSeq":bseq,"menuSeq":4804,"subPageIndex":1,"pageIndex":"","searchCondition":"","searchKeyword":""},timeout=60)
        s=BeautifulSoup(r.text,"lxml")
        arts=[(a.get("href"),a.get_text(" ",strip=True)) for a in s.find_all("a") if "articleSeq=" in (a.get("href") or "")]
        print("   board",bseq,len(r.content),len(arts))
        for i,(h,t) in enumerate(arts[:2]):
            r2,s2=soup(urljoin("https://www.daejeon.go.kr",h))
            dl=[a.get("href") for a in s2.find_all("a") if re.search(r"(?i)download|FileDown",a.get("href") or "")]
            if dl: save("daejeon_city",urljoin("https://www.daejeon.go.kr",dl[0]),t,n=f"{bseq}_{i}")
            else: print("  no attach",t[:50])
@task
def daejeon_donggu():
    r,s=soup("https://www.donggu.go.kr/kr/open/secretBusiness/list.do")
    print("  donggu list",len(r.content), [a.get("onclick") or a.get("href") for a in s.select(".notice_list a")][:4])

run(sys.argv[1:])
prev=json.load(open("fetch_log.json",encoding="utf-8")) if os.path.exists("fetch_log.json") else []
json.dump(prev+LOG,open("fetch_log.json","w",encoding="utf-8"),ensure_ascii=False,indent=1)
