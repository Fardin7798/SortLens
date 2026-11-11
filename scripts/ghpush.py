"""Push the staged index (relative to main) as one commit on a branch via GitHub API.
Set SORTLENS_REPO=owner/name (e.g. Fardin7798/sortlens). Auth is added by the environment, never stored here."""
import base64, os, subprocess, sys, httpx
R="https://api.github.com/repos/"+os.environ["SORTLENS_REPO"]
S=httpx.Client(headers={"Accept":"application/vnd.github+json"},timeout=60)
def j(r):
    if r.status_code>=300: print(r.status_code, r.text[:300]); sys.exit(1)
    return r.json()
branch, msg = sys.argv[1], sys.argv[2]
main=j(S.get(f"{R}/git/ref/heads/main"))["object"]["sha"]
r=S.get(f"{R}/git/ref/heads/{branch}")
parent=r.json()["object"]["sha"] if r.status_code==200 else main
basetree=j(S.get(f"{R}/git/commits/{main}"))["tree"]["sha"]
out=subprocess.check_output(["git","diff","--cached","--name-status","--no-renames",main]).decode().splitlines()
tree=[]
for line in out:
    st,path=line.split("\t",1)
    if st=="D": tree.append({"path":path,"mode":"100644","type":"blob","sha":None}); continue
    b=j(S.post(f"{R}/git/blobs",json={"content":base64.b64encode(open(path,"rb").read()).decode(),"encoding":"base64"}))
    tree.append({"path":path,"mode":"100644","type":"blob","sha":b["sha"]})
t=j(S.post(f"{R}/git/trees",json={"base_tree":basetree,"tree":tree}))
local=subprocess.check_output(["git","write-tree"]).decode().strip()
print("tree match:", t["sha"]==local)
c=j(S.post(f"{R}/git/commits",json={"message":msg,"tree":t["sha"],"parents":[parent]}))
if r.status_code==200: j(S.patch(f"{R}/git/refs/heads/{branch}",json={"sha":c["sha"]}))
else: j(S.post(f"{R}/git/refs",json={"ref":f"refs/heads/{branch}","sha":c["sha"]}))
print("pushed", branch, c["sha"], "parent", parent[:7])
