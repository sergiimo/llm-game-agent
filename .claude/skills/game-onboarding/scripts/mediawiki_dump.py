import json, sys, os, urllib.request, urllib.parse, time
A="https://wylde-flowers.fandom.com/api.php"
out=sys.argv[2]; os.makedirs(out, exist_ok=True)
titles=[t.strip() for t in open(sys.argv[1]) if t.strip()]
for i in range(0,len(titles),50):
    chunk=titles[i:i+50]
    q=urllib.parse.urlencode({"action":"query","prop":"revisions","rvprop":"content","rvslots":"main","format":"json","titles":"|".join(chunk)})
    req=urllib.request.Request(A+"?"+q, headers={"User-Agent":"Mozilla/5.0 (Macintosh) Safari/605.1.15"})
    d=json.load(urllib.request.urlopen(req, timeout=60))
    for p in d["query"]["pages"].values():
        try: txt=p["revisions"][0]["slots"]["main"]["*"]
        except Exception: continue
        fn=p["title"].replace("/","__").replace(":","_")+".wiki"
        open(os.path.join(out,fn),"w").write(txt)
    time.sleep(0.3)
print("done")
