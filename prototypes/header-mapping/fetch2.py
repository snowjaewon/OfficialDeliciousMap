import re, json, os
from urllib.parse import urljoin, quote
exec(open("fetch.py",encoding="utf-8").read().split("run(sys.argv[1:])")[0])
TASKS.clear()
@task
def daejeon_city2():
    for bseq,lab in [(694,"과장"),(1186,"시장"),(747,"국장")]:
        r=S.post("https://www.daejeon.go.kr/drh/open/drhDataOpen/drhDataOpenBoardView.do",data={"boardSeq":bseq,"menuSeq":4804,"subPageIndex":1,"pageIndex":"","searchCondition":"","searchKeyword":""},timeout=60)
        s=BeautifulSoup(r.text,"lxml")
        arts=[(a.get("href"),a.get_text(" ",strip=True)) for a in s.find_all("a") if "articleSeq=" in (a.get("href") or "")]
        for i,(h,t) in enumerate(arts[:3]):
            r2,s2=soup(urljoin("https://www.daejeon.go.kr",h))
            for a in s2.find_all("a"):
                m=re.search(r"fileDownLoad\('([^']+)',\s*'([^']+)'",a.get("href") or "")
                if m:
                    save("daejeon_city",f"https://www.daejeon.go.kr/cmm/Download.do?filePath={quote(m.group(1))}&fileName={quote(m.group(2))}",f"{lab} {t} {m.group(2)}",n=f"{bseq}_{i}"); break
@task
def busan_seo2():
    links,_=list_links("https://www.bsseogu.go.kr/board/list.bsseogu?boardId=BBS_0000151",r"view\.",max_n=3)
    for i,(h,t) in enumerate(links):
        r,s=soup(urljoin("https://www.bsseogu.go.kr",h.split()[0]))
        dl=[a.get("href") for a in s.find_all("a") if "download." in (a.get("href") or "")]
        if dl: save("busan_seo",urljoin("https://www.bsseogu.go.kr",dl[0]),t,n=i)
@task
def incheon_jemulpo2():
    links,_=list_links("https://www.jemulpo.go.kr/main/bbs/bbsMsgList.do?bcd=opendata",r"msg_seq=\d+",max_n=3,prefer=lambda t:"업무추진비" in t)
    for i,(h,t) in enumerate(links):
        seq=re.search(r"msg_seq=(\d+)",h).group(1)
        save("incheon_jemulpo",f"https://www.jemulpo.go.kr/main/bbs/bbsMsgFileDown.do?bcd=opendata&msg_seq={seq}&fileno=1",t,referer="https://www.jemulpo.go.kr",n=i)
@task
def incheon_namdong2():
    for base,bcd,key in [("https://www.namdong.go.kr/main","expense","incheon_namdong"),("https://www.icbp.go.kr/main","expense","incheon_bupyeong")]:
        try:
            links,r=list_links(f"{base}/bbs/bbsMsgList.do?bcd={bcd}",r"msg_seq=\d+",max_n=2)
            print("   ",key,len(r.content),len(links))
            for i,(h,t) in enumerate(links):
                seq=re.search(r"msg_seq=(\d+)",h).group(1)
                save(key,f"{base}/bbs/bbsMsgFileDown.do?bcd={bcd}&msg_seq={seq}&fileno=1",t,referer=base,n=i)
        except Exception as e: print("  ",key,e)
run([])
prev=json.load(open("fetch_log.json",encoding="utf-8"))
json.dump(prev+LOG,open("fetch_log.json","w",encoding="utf-8"),ensure_ascii=False,indent=1)
